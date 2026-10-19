"""Role administration: CRUD and permission binding.

Rules:

- Permission codes are validated against the code-defined catalog (ADR-0003):
  binding an unknown code is a 400, not silent data.
- System roles (`is_system`, seeded by migration 0001) cannot be deleted and
  their `code` is immutable — other modules reference `'admin'`/`'user'` by
  code (e.g. the last-admin guard, OIDC default role).
- The ``admin`` role always holds exactly the superuser wildcard ``*``
  (ADR-0021). Only a caller who already holds ``*`` may grant or revoke it,
  and only such a caller may edit a custom role that holds it. The checks live
  here rather than only in the router so every internal caller gets the same
  boundary; ``actor=None`` marks an in-process caller with no request identity.
  It may manage ordinary roles, but it cannot grant or touch the wildcard —
  only a verified ``*`` holder can.
- Assigning roles to users validates that every id exists (FK would catch it,
  but a clean 400 beats an IntegrityError 500).
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.user.auth.dependencies import Viewer
from cliver_playbook.app.user.auth.permissions import ALL_PERMISSIONS, permission_codes
from cliver_playbook.app.user.models.entities import Role, RolePermission
from cliver_playbook.app.user.services.users import DomainError

ADMIN_ROLE_CODE = "admin"


async def get_role(db: AsyncSession, role_id: int) -> Role | None:
    return (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()


async def list_roles(db: AsyncSession) -> list[dict]:
    """All roles with their permission codes, sorted by code."""
    roles = (await db.execute(select(Role).order_by(Role.code))).scalars().all()
    if not roles:
        return []
    perms = await db.execute(select(RolePermission))
    by_role: dict[int, set[str]] = {}
    for row in perms.scalars():
        by_role.setdefault(row.role_id, set()).add(row.permission_code)
    return [
        {
            "role": role,
            "permission_codes": sorted(by_role.get(role.id, set())),
        }
        for role in roles
    ]


def _normalise_codes(codes: list[str]) -> list[str]:
    """Validate and canonicalise a role's permission set.

    The wildcard subsumes every other code, so ``*`` plus anything else is
    stored as just ``*``. That keeps the invariant "a superuser role's set is
    exactly ``["*"]``" cheap to assert everywhere.
    """
    unknown = [c for c in codes if c not in permission_codes()]
    if unknown:
        raise DomainError(
            f"Unknown permission codes: {', '.join(sorted(unknown))} — "
            "see GET /api/v1/admin/permissions for the catalog.",
            status_code=400,
        )
    if len(codes) != len(set(codes)):
        raise DomainError("Duplicate permission codes in request.", status_code=400)
    if ALL_PERMISSIONS in codes:
        return [ALL_PERMISSIONS]
    return codes


def _validate_codes(codes: list[str]) -> None:
    _normalise_codes(codes)


async def _current_codes(db: AsyncSession, role_id: int) -> set[str]:
    rows = await db.execute(
        select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
    )
    return set(rows.scalars().all())


def _assert_can_bind(codes: list[str], actor: Viewer | None) -> None:
    """Only a superuser may hand out the superuser wildcard."""
    if ALL_PERMISSIONS in codes and (actor is None or not actor.has(ALL_PERMISSIONS)):
        raise DomainError(
            "Only a user holding the '*' permission can grant it.",
            status_code=403,
        )


def _assert_can_modify(current: set[str], actor: Viewer | None) -> None:
    """A role that holds the wildcard is a superuser role: only a superuser
    may edit or delete it, even if the caller otherwise holds ``role:manage``."""
    if ALL_PERMISSIONS in current and (actor is None or not actor.has(ALL_PERMISSIONS)):
        raise DomainError(
            "Only a user holding the '*' permission can modify a superuser role.",
            status_code=403,
        )


async def validate_role_ids(db: AsyncSession, role_ids: list[int]) -> list[int]:
    """Ensure every id resolves to an existing role; returns deduplicated ids."""
    unique = list(dict.fromkeys(role_ids))
    found = (await db.execute(select(Role.id).where(Role.id.in_(unique)))).scalars().all()
    if len(found) != len(unique):
        raise DomainError("One or more role ids do not exist.", status_code=400)
    return unique


async def create_role(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    description: str,
    permission_codes: list[str],
    actor: Viewer | None = None,
) -> Role:
    _assert_can_bind(permission_codes, actor)
    _validate_codes(permission_codes)
    existing = (await db.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
    if existing is not None:
        raise DomainError(f"Role code '{code}' is already taken.", status_code=409)
    role = Role(code=code, name=name, description=description)
    db.add(role)
    await db.flush()
    await set_role_permissions(db, role, permission_codes, actor=actor)
    return role


async def update_role(
    db: AsyncSession,
    role: Role,
    *,
    name: str | None = None,
    description: str | None = None,
    code: str | None = None,
    permission_codes: list[str] | None = None,
    actor: Viewer | None = None,
) -> Role:
    current = await _current_codes(db, role.id)
    _assert_can_modify(current, actor)
    if permission_codes is not None:
        _assert_can_bind(permission_codes, actor)
        if role.code == ADMIN_ROLE_CODE and _normalise_codes(permission_codes) != [ALL_PERMISSIONS]:
            raise DomainError(
                "The system administrator role always holds all permissions.",
                status_code=400,
            )
    if code is not None and code != role.code:
        if role.is_system:
            raise DomainError(f"System role '{role.code}' cannot be renamed.", status_code=400)
        clash = (await db.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
        if clash is not None:
            raise DomainError(f"Role code '{code}' is already taken.", status_code=409)
        role.code = code
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    await db.flush()
    if permission_codes is not None:
        await set_role_permissions(db, role, permission_codes, actor=actor)
    return role


async def set_role_permissions(
    db: AsyncSession,
    role: Role,
    permission_codes: list[str],
    *,
    actor: Viewer | None = None,
) -> None:
    """Replace the role's permission set wholesale (full-state PUT semantics).

    The set is canonicalised: if it contains ``*`` it is stored as exactly
    ``["*"]``. The admin system role is pinned to that set for the lifetime of
    the installation.
    """
    normalised = _normalise_codes(permission_codes)
    _assert_can_bind(normalised, actor)
    current = await _current_codes(db, role.id)
    _assert_can_modify(current, actor)
    if role.code == ADMIN_ROLE_CODE and normalised != [ALL_PERMISSIONS]:
        raise DomainError(
            "The system administrator role always holds all permissions.",
            status_code=400,
        )
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for code in normalised:
        db.add(RolePermission(role_id=role.id, permission_code=code))
    await db.flush()


async def delete_role(db: AsyncSession, role: Role, *, actor: Viewer | None = None) -> None:
    _assert_can_modify(await _current_codes(db, role.id), actor)
    if role.is_system:
        raise DomainError(f"System role '{role.code}' cannot be deleted.", status_code=400)
    await db.delete(role)
    await db.flush()
