"""The seeded admin holds the MCP permission codes on a fresh database.

The identity package's migration seeds the admin role from the *live* catalog
(``permission_catalog()``, called at seed time), and this package registers its
``mcp:*`` codes into that catalog when it is imported (ADR-0017). Composing the
two therefore grants the MCP codes to admin on a fresh install with no extra
step, while a deployment that installs only the identity package has no trace
of them. That is the whole point of registration over editing the catalog
literal, and it is what these tests pin.

They drive the shipped migration code itself — loaded from the identity
package's installed ``alembic/versions/`` — rather than a re-implementation:
the failure being guarded against is a future edit that hardcodes a permission
list in the migration and silently drops whatever the surrounding deployment
registers.

Per-role enforcement (a viewer missing one of the codes is denied) is covered
in ``test_mcp_tools.py``; this file is about the seed.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text

import cliver_playbook.app.user.alembic as user_alembic
from cliver_playbook.app.mcp.permissions import MCP_PERMISSION_CODES
from cliver_playbook.app.mcp.settings import settings
from cliver_playbook.app.user.auth.permissions import permission_catalog
from cliver_playbook.app.user.models.entities import User

# The chain that creates and seeds the identity tables, located inside the
# installed package: the mcp suite exercises the real migration, and resolving
# it this way keeps the path correct no matter where the package is installed.
_USER_MIGRATION = (
    Path(user_alembic.__file__).resolve().parent / "versions" / "0001_user_management.py"
)


def _load_migration() -> Any:
    """Import the identity migration file as a module so its _seed() is callable."""
    spec = importlib.util.spec_from_file_location("migration_0001_user_management", _USER_MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_seed(module: Any) -> None:
    """Run the migration's _seed() on the sync driver with alembic's op bound.

    ``Operations.context`` installs the op proxy that ``_seed`` reads via
    ``op.get_bind()`` — the same binding alembic itself provides during a
    real upgrade. Sync driver on purpose: migrations never touch the
    async engine.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine(settings.sync_db_url)
    try:
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            module._seed()
    finally:
        engine.dispose()


async def _admin_permission_codes(db: Any) -> list[str]:
    rows = await db.execute(
        text(
            "SELECT rp.permission_code FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id WHERE r.code = 'admin'"
        )
    )
    return list(rows.scalars().all())


class _FixedSettings:
    """Seed stand-in with a fixed password: the generated-password banner is
    for humans reading migration output, not for test logs."""

    initial_admin_password = "seed-test-password"


async def test_seed_grants_admin_the_live_catalog_including_mcp(db, monkeypatch):
    """Fresh-database seed: admin holds every catalog code — the four mcp:*
    codes included, because this package registered them at import — the
    baseline user role exists with no permissions, and the admin account
    forces a password change on first login."""
    module = _load_migration()
    monkeypatch.setattr(module, "get_settings", lambda: _FixedSettings())

    await asyncio.to_thread(_run_seed, module)

    codes = await _admin_permission_codes(db)
    assert len(codes) == len(set(codes)) == len(permission_catalog())
    for code in MCP_PERMISSION_CODES:
        assert code in codes, f"fresh seed is missing {code!r} for the admin role"

    user_role_perms = await db.execute(
        text(
            "SELECT count(*) FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id WHERE r.code = 'user'"
        )
    )
    assert user_role_perms.scalar_one() == 0  # baseline role is permission-less

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    # The seeded password is printed once and never stored: whoever logs in
    # must rotate it before the account can do anything else.
    assert admin.must_change_password is True
    assert admin.is_active is True


async def test_seed_is_rerunnable_without_duplicates(db, monkeypatch):
    """Re-running the seed on an already-seeded database is a no-op —
    the guards exist for downgrade/re-upgrade cycles and scripted
    re-seeds; this pins that behaviour."""
    module = _load_migration()
    monkeypatch.setattr(module, "get_settings", lambda: _FixedSettings())

    await asyncio.to_thread(_run_seed, module)
    await asyncio.to_thread(_run_seed, module)

    codes = await _admin_permission_codes(db)
    assert len(codes) == len(permission_catalog())  # no duplicate grants
    users = (await db.execute(select(User).where(User.username == "admin"))).scalars().all()
    assert len(users) == 1
