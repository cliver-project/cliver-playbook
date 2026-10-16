"""The permission catalog — a code-defined, fixed list (ADR-0003).

There is deliberately NO `permissions` table. Permissions are compile-time
facts of the application: every code that exists has a `require_perm()` call
site somewhere in the routers. A database table would allow admins to bind
nonexistent codes (drift) and would need seeding/migration on every code change.
The catalog here is the single source of truth; roles bind codes from it, and
`PUT /roles/{id}/permissions` rejects anything outside it.

Adding a permission = add a row here + a `require_perm("...")` call site in one
commit. The admin role seed in migration 0002 reads this catalog, so a fresh
database automatically grants the admin role every new permission.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    """One grantable capability. `code` is the stable wire/API identifier."""

    code: str
    name: str
    group: str


PERMISSION_CATALOG: tuple[Permission, ...] = (
    # User administration
    Permission("user:read", "View users", "Users"),
    Permission("user:create", "Create users", "Users"),
    Permission("user:update", "Edit users and assign roles", "Users"),
    Permission("user:delete", "Delete users", "Users"),
    Permission("user:reset_password", "Reset another user's password", "Users"),
    Permission("user:force_logout", "Revoke another user's sessions", "Users"),
    # Role administration
    Permission("role:read", "View roles and permission bindings", "Roles"),
    Permission("role:manage", "Create/edit roles and bind permissions", "Roles"),
    # Compliance
    Permission("audit:read", "Read the audit log", "Audit"),
    # OAuth 2.1 provider administration (ADR-0005)
    Permission("oauth:read", "View registered clients and active grants", "OAuth"),
    Permission("oauth:revoke", "Revoke OAuth grants (user × client)", "OAuth"),
)

PERMISSION_CODES: frozenset[str] = frozenset(p.code for p in PERMISSION_CATALOG)


def catalog_as_dicts() -> list[dict]:
    """Serializable dump for `GET /api/v1/admin/permissions` (admin UI pickers)."""
    return [{"code": p.code, "name": p.name, "group": p.group} for p in PERMISSION_CATALOG]
