"""Role administration: CRUD and permission binding.

Rules:

- Permission codes are validated against the code-defined catalog (ADR-0003):
  binding an unknown code is a 400, not silent data.
- System roles (`is_system`, seeded by migration 0002) cannot be deleted and
  their `code` is immutable — other modules reference `'admin'`/`'user'` by
  code (e.g. the last-admin guard, OIDC default role).
- Assigning roles to users validates that every id exists (FK would catch it,
  but a clean 400 beats an IntegrityError 500).
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import PERMISSION_CODES
from app.models.entities import Role, RolePermission
from app.services.users import DomainError


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


def _validate_codes(codes: list[str]) -> None:
    unknown = [c for c in codes if c not in PERMISSION_CODES]
    if unknown:
        raise DomainError(
            f"Unknown permission codes: {', '.join(sorted(unknown))} — "
            "see GET /api/v1/admin/permissions for the catalog.",
            status_code=400,
        )
    if len(codes) != len(set(codes)):
        raise DomainError("Duplicate permission codes in request.", status_code=400)


async def validate_role_ids(db: AsyncSession, role_ids: list[int]) -> list[int]:
    """Ensure every id resolves to an existing role; returns deduplicated ids."""
    unique = list(dict.fromkeys(role_ids))
    found = (await db.execute(select(Role.id).where(Role.id.in_(unique)))).scalars().all()
    if len(found) != len(unique):
        raise DomainError("One or more role ids do not exist.", status_code=400)
    return unique


async def create_role(
    db: AsyncSession, *, code: str, name: str, description: str, permission_codes: list[str]
) -> Role:
    _validate_codes(permission_codes)
    existing = (await db.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
    if existing is not None:
        raise DomainError(f"Role code '{code}' is already taken.", status_code=409)
    role = Role(code=code, name=name, description=description)
    db.add(role)
    await db.flush()
    await set_role_permissions(db, role, permission_codes)
    return role


async def update_role(
    db: AsyncSession,
    role: Role,
    *,
    name: str | None = None,
    description: str | None = None,
    code: str | None = None,
    permission_codes: list[str] | None = None,
) -> Role:
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
        await set_role_permissions(db, role, permission_codes)
    return role


async def set_role_permissions(db: AsyncSession, role: Role, permission_codes: list[str]) -> None:
    """Replace the role's permission set wholesale (full-state PUT semantics)."""
    _validate_codes(permission_codes)
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for code in permission_codes:
        db.add(RolePermission(role_id=role.id, permission_code=code))
    await db.flush()


async def delete_role(db: AsyncSession, role: Role) -> None:
    if role.is_system:
        raise DomainError(f"System role '{role.code}' cannot be deleted.", status_code=400)
    await db.delete(role)
    await db.flush()
