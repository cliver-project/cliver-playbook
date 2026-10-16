"""User administration: CRUD, role assignment, credentials, self-protections.

Guards encoded here (each mirrored by a test):

- **Never self-delete / self-deactivate / self-demote.** An admin editing their
  own account can lock themselves — and every other admin — out mid-operation.
  Rule: `actor.id == target.id` + a state-changing operation is rejected for
  anything except `set_password` (self password change is the normal flow).
- **Never remove the last active admin.** Deleting, deactivating, or stripping
  the admin role from the only active admin-role holder is rejected — otherwise
  a misclick bricks the installation's management surface.

Lockout lives here too: authenticate() counts consecutive failures and locks
the account for `login_lockout_minutes` after `login_lockout_threshold`
failures. The counter resets on success.
"""

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.user.auth.passwords import verify_password
from cliver_playbook.app.user.auth.tokens import revoke_all_for_user
from cliver_playbook.app.user.models.entities import Role, RolePermission, User, UserRole
from cliver_playbook.app.user.settings import get_settings
from cliver_playbook.app.user.timeutil import utcnow

ADMIN_ROLE_CODE = "admin"

# Sentinel distinguishing "field absent from the request" (leave unchanged)
# from "field explicitly sent as null/empty" (clear it). Pydantic alone
# cannot express the difference with `X | None = None` defaults; routers build
# kwargs from `payload.model_fields_set` and pass only what was sent.
_UNSET: object = object()


class DomainError(Exception):
    """Rule violation that maps to HTTP 400/403/404 depending on context."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()


async def list_users(db: AsyncSession, q: str | None = None) -> list[dict]:
    """All users with their role codes and flattened permission codes,
    optionally filtered by substring.

    Sorted by username — stable for UIs and tests. DISTINCT inside the
    aggregates because the role×permission join fans rows out.
    """
    stmt = (
        select(
            User,
            func.coalesce(func.string_agg(func.distinct(Role.code), ","), ""),
            func.coalesce(func.string_agg(func.distinct(RolePermission.permission_code), ","), ""),
        )
        .outerjoin(UserRole, UserRole.user_id == User.id)
        .outerjoin(Role, Role.id == UserRole.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .group_by(User.id)
        .order_by(User.username)
    )
    if q:
        stmt = stmt.where(User.username.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    rows = await db.execute(stmt)
    return [
        {
            "user": user,
            "role_codes": sorted(code for code in roles.split(",") if code),
            "permission_codes": sorted(code for code in perms.split(",") if code),
        }
        for user, roles, perms in rows
    ]


# ---------------------------------------------------------------------------
# Self-protection helpers
# ---------------------------------------------------------------------------


async def count_active_admins(db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count(User.id))
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == ADMIN_ROLE_CODE, User.is_active.is_(True))
        )
    ).scalar_one()


async def _role_codes_for_user(db: AsyncSession, user_id: int) -> set[str]:
    rows = await db.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return {code for (code,) in rows}


async def permission_codes_for_user(db: AsyncSession, user_id: int) -> set[str]:
    """Flattened permission codes across all roles — for SPA display gating."""
    rows = await db.execute(
        select(RolePermission.permission_code)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return {code for (code,) in rows}


async def assert_not_last_admin_removed(
    db: AsyncSession, target: User, *, removing_admin_role: bool, deactivating: bool
) -> None:
    """Reject operations that would leave zero active admin-role users.

    `removing_admin_role`/`deactivating` describe what the caller is about to
    do to `target`; both False = nothing that endangers admin access.
    """
    if not (removing_admin_role or deactivating):
        return
    roles = await _role_codes_for_user(db, target.id)
    if ADMIN_ROLE_CODE not in roles or not target.is_active:
        return  # target is not an active admin; removing them changes nothing
    admins = await count_active_admins(db)
    if admins <= 1:
        raise DomainError(
            "Cannot remove the last active admin — grant the admin role to "
            "another active user first.",
            status_code=400,
        )


def assert_not_self_mutation(actor_id: int, target_id: int, *, what: str) -> None:
    if actor_id == target_id:
        raise DomainError(f"Admins cannot {what} their own account.", status_code=400)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def set_user_roles(
    db: AsyncSession, user_id: int, role_ids: list[int], *, granted_by: int | None = None
) -> None:
    """Replace the user's role set wholesale (idempotent full-state PUT)."""
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    for role_id in role_ids:
        db.add(UserRole(user_id=user_id, role_id=role_id, granted_by=granted_by))
    await db.flush()


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password_hash: str,
    email: str | None,
    phone: str | None = None,
    display_name: str,
    role_ids: list[int],
    must_change_password: bool = True,
    granted_by: int | None = None,
) -> User:
    if await get_user_by_username(db, username) is not None:
        raise DomainError(f"Username '{username}' is already taken.", status_code=409)
    user = User(
        username=username,
        email=email,
        phone=phone,
        password_hash=password_hash,
        display_name=display_name or username,
        must_change_password=must_change_password,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Race-safe uniqueness enforcement (uq_users_email): the database is
        # the authority, a pre-check SELECT cannot be. Rollback first — the
        # session is poisoned after a failed flush.
        await db.rollback()
        raise DomainError("Email is already in use by another account.", status_code=409) from exc
    await set_user_roles(db, user.id, role_ids, granted_by=granted_by)
    return user


async def update_user(
    db: AsyncSession,
    target: User,
    *,
    actor_id: int,
    email: str | None | object = _UNSET,
    phone: str | None | object = _UNSET,
    display_name: str | None | object = _UNSET,
    is_active: bool | None = None,
    role_ids: list[int] | object = _UNSET,
) -> User:
    """Update profile/activation/roles with self- and last-admin protection.

    `_UNSET` means "leave unchanged"; an explicit `None` for email/phone
    CLEARS the field; `role_ids` (when provided) replaces the full role set.
    is_active toggles account status; on deactivation every token is revoked
    (no lingering sessions).
    """
    current_roles = await _role_codes_for_user(db, target.id)

    if is_active is False:
        assert_not_self_mutation(actor_id, target.id, what="deactivate")
    if role_ids is not _UNSET and ADMIN_ROLE_CODE in current_roles:
        # Will this edit strip the admin role?
        new_role_ids = set(role_ids)
        new_roles: set[str] = set()
        if new_role_ids:
            rows = await db.execute(select(Role.id, Role.code).where(Role.id.in_(new_role_ids)))
            new_roles = {code for _, code in rows}
        if ADMIN_ROLE_CODE not in new_roles:
            assert_not_self_mutation(actor_id, target.id, what="remove own admin role from")
            await assert_not_last_admin_removed(
                db, target, removing_admin_role=True, deactivating=False
            )

    if is_active is False:
        await assert_not_last_admin_removed(
            db, target, removing_admin_role=False, deactivating=True
        )

    if email is not _UNSET:
        target.email = email or None  # type: ignore[assignment]
    if phone is not _UNSET:
        target.phone = phone or None  # type: ignore[assignment]
    if display_name is not _UNSET and display_name:
        target.display_name = str(display_name)
    if is_active is not None:
        target.is_active = is_active
        if is_active is False:
            # Revoke through the shared choke point so OAuth refresh tokens
            # die too — otherwise a later reactivation would silently revive
            # every agent grant issued before the deactivation.
            await revoke_all_for_user(db, target.id)
    if role_ids is not _UNSET:
        await set_user_roles(db, target.id, list(role_ids), granted_by=actor_id)  # type: ignore[arg-type]
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DomainError("Email is already in use by another account.", status_code=409) from exc
    return target


async def update_own_profile(
    db: AsyncSession,
    user: User,
    *,
    email: str | None | object = _UNSET,
    phone: str | None | object = _UNSET,
    display_name: str | None | object = _UNSET,
) -> User:
    """Self-service profile edit — the narrow sibling of update_user: no
    roles, no activation, no username (stable identity), no admin guards
    (the caller IS the target).

    Same `_UNSET` convention as update_user: absent = unchanged, explicit
    None = clear (the schema validator normalizes "" to None), non-empty
    value = set. Email uniqueness is race-safe via the same IntegrityError
    catch — the database is the authority.
    """
    if email is not _UNSET:
        user.email = email or None  # type: ignore[assignment]
    if phone is not _UNSET:
        user.phone = phone or None  # type: ignore[assignment]
    if display_name is not _UNSET and display_name:
        user.display_name = str(display_name)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DomainError("Email is already in use by another account.", status_code=409) from exc
    return user


async def delete_user(db: AsyncSession, target: User, *, actor_id: int) -> None:
    assert_not_self_mutation(actor_id, target.id, what="delete")
    await assert_not_last_admin_removed(
        db, target, removing_admin_role=target.is_active, deactivating=target.is_active
    )
    await db.delete(target)
    await db.flush()


async def admin_reset_password(db: AsyncSession, target: User, new_password_hash: str) -> None:
    """Set a new password on behalf of an admin: force change on next login and
    revoke every credential (all sessions, static tokens, OAuth access AND
    refresh tokens drop immediately — the credential they authenticated with
    is no longer current, and grants issued under it must not survive it)."""
    target.password_hash = new_password_hash
    target.must_change_password = True
    target.failed_login_attempts = 0
    target.locked_until = None
    await revoke_all_for_user(db, target.id)
    await db.flush()


async def set_password(db: AsyncSession, user: User, new_password_hash: str) -> None:
    """Self-service password change: clears the must-change flag.

    Token revocation is the caller's job (the API layer revokes all, then
    re-issues one fresh web token so the current browser stays logged in).
    """
    user.password_hash = new_password_hash
    user.must_change_password = False
    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class AuthenticateResult:
    __slots__ = ("reason", "user")

    def __init__(self, user: User | None, reason: str | None) -> None:
        self.user = user
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.user is not None


async def authenticate(db: AsyncSession, username: str, password: str) -> AuthenticateResult:
    """Verify credentials with brute-force lockout.

    Reasons: "invalid" (bad username/password — deliberately identical for
    both, so the endpoint cannot be used to enumerate usernames), "locked",
    "inactive". On failure the counter bumps; reaching the threshold locks the
    account for the configured window. On success the counter clears.
    """
    settings = get_settings()
    now = utcnow()

    user = await get_user_by_username(db, username)
    if user is None:
        # Burn comparable CPU so timing does not reveal username existence.
        verify_password(password, "pbkdf2_sha256$1$00$00")
        return AuthenticateResult(None, "invalid")

    if user.locked_until is not None and user.locked_until > now:
        return AuthenticateResult(None, "locked")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.login_lockout_threshold:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_attempts = 0  # window restarts on unlock
        await db.flush()
        return AuthenticateResult(None, "invalid")

    if not user.is_active:
        return AuthenticateResult(None, "inactive")

    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()
    return AuthenticateResult(user, None)
