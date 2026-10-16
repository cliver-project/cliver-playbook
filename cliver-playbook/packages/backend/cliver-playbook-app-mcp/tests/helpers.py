"""Shared test helpers for the MCP suites.

`seed_admin` re-creates what the identity package's migration seeds — the
autouse TRUNCATE fixture wipes it between tests, so each test seeds exactly
what it needs. The permission set it grants is read from the live catalog
(``permission_catalog()``, not an imported snapshot), which is what makes the
MCP suites meaningful: importing this package registered the ``mcp:*`` codes,
so the seeded admin holds them — the same way a real fresh install does.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.user.auth.passwords import hash_password
from cliver_playbook.app.user.auth.permissions import permission_catalog
from cliver_playbook.app.user.models.entities import Role, RolePermission, User, UserRole

TEST_ADMIN_PASSWORD = "admin-test-passw0rd"


async def seed_admin(session: AsyncSession) -> int:
    """Seed system roles + an admin user with the full permission set."""
    admin_role = Role(code="admin", name="Administrator", is_system=True)
    user_role = Role(code="user", name="User", is_system=True)
    session.add_all([admin_role, user_role])
    await session.flush()
    for perm in permission_catalog():
        session.add(RolePermission(role_id=admin_role.id, permission_code=perm.code))
    admin_user = User(
        username="admin",
        password_hash=hash_password(TEST_ADMIN_PASSWORD),
        display_name="Admin",
        must_change_password=False,
    )
    session.add(admin_user)
    await session.flush()
    session.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
    await session.commit()
    return admin_user.id


async def login(client, username: str, password: str) -> str:
    """Login helper returning the bearer token (asserts success)."""
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]
