"""Request authentication and permission dependencies.

The enforcement chain (ADR-0003):

    Bearer token --verify_bearer--> user row --load_viewer--> Viewer
    --> get_current_user (must-change-password gate) --> require_perm(code)

Everything an endpoint learns about the caller comes from `Viewer`, resolved
from the database on every request — never from claims embedded in the token.
The token is only a lookup key; this is what makes revocation instant and
permission changes effective on the very next request.
"""

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.user.auth.permissions import permission_codes
from cliver_playbook.app.user.auth.tokens import verify_bearer
from cliver_playbook.app.user.models.entities import Role, RolePermission, User, UserRole

# Paths a user under the must-change-password gate may still call. Login is
# exempt by construction (it is not authenticated); logout and changing the
# password obviously must remain reachable, and /me lets the frontend render
# its "change your password" screen. /profile edits only the caller's own
# contact details (no credentials, no privileges), so the gate does not need
# to block it either.
_MUST_CHANGE_ALLOWED_PATHS = frozenset(
    {
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
        "/api/v1/auth/profile",
    }
)


@dataclass
class Viewer:
    """The authenticated caller, resolved fresh from the database per request."""

    user_id: int
    username: str
    display_name: str
    must_change_password: bool
    role_codes: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    token_id: int | None = None

    def has(self, code: str) -> bool:
        return code in self.permissions


async def load_viewer(
    db: AsyncSession, user_id: int, *, token_id: int | None = None
) -> Viewer | None:
    """Resolve a user to a Viewer with role codes and permission codes.

    Returns None if the user no longer exists or has been deactivated — both
    must invalidate outstanding tokens (deactivation is effective immediately,
    not at token expiry).
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    rows = await db.execute(
        select(Role.code, RolePermission.permission_code)
        .select_from(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    roles: set[str] = set()
    perms: set[str] = set()
    for role_code, perm_code in rows:
        roles.add(role_code)
        if perm_code is not None:
            perms.add(perm_code)

    return Viewer(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        must_change_password=user.must_change_password,
        role_codes=frozenset(roles),
        permissions=frozenset(perms),
        token_id=token_id,
    )


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> Viewer:
    """Authenticate the request via its Bearer token and apply the
    must-change-password gate.

    401 covers unknown/expired/revoked tokens; 403 with code
    `must_change_password` traps a credential that must be rotated before the
    account can do anything else — the frontend intercepts that code and
    routes to the change-password screen (server-enforced, not just UI).
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = await verify_bearer(db, token)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    viewer = await load_viewer(db, row.user_id, token_id=row.id)
    if viewer is None:
        # Token row exists but the user is gone/deactivated since issuance.
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if viewer.must_change_password and request.url.path not in _MUST_CHANGE_ALLOWED_PATHS:
        raise HTTPException(
            status_code=403,
            detail={"code": "must_change_password"},
        )
    return viewer


def require_perm(code: str):
    """FastAPI dependency factory: the caller must hold `code`.

    Codes are validated against the live catalog at import time — a typo in a
    router (say `user:reed`) would otherwise 403 every request with no hint,
    and worse, a binding to a nonexistent code would silently grant nothing.
    "Live" matters for composition: a package that registers its codes
    (ADR-0017) must do so before the module defining this call site imports.
    """
    if code not in permission_codes():
        raise RuntimeError(
            f"require_perm({code!r}): not in the permission catalog — add it to "
            "auth/permissions.py (this package) or register it from the owning "
            "package before this route module imports"
        )

    async def _checker(viewer: Viewer = Depends(get_current_user)) -> Viewer:
        if not viewer.has(code):
            raise HTTPException(status_code=403, detail=f"Missing permission: {code}")
        return viewer

    return _checker
