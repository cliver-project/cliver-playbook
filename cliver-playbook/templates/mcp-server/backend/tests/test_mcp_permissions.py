"""The seeded admin holds the MCP permissions on a fresh database.

Migration 0002 seeds the admin role from ``PERMISSION_CATALOG``
dynamically, so the ``mcp:*`` codes this template adds to the catalog
are granted without touching the migration — admin gets them on every
fresh install. These tests drive the shipped migration code itself
(loaded from ``alembic/versions/``), not a re-implementation: the
failure they guard against is a future edit that hardcodes a
permission list in 0002 and silently drops the MCP codes on fresh
databases.

Per-role enforcement (a viewer missing one of the codes is denied) is
covered in ``test_mcp_tools.py``; this file is about the seed.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text

from app.auth.permissions import PERMISSION_CATALOG
from app.core.config import settings
from app.mcp.permissions import MCP_PERMISSION_CODES
from app.models.entities import User

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_migration() -> Any:
    """Import alembic/versions/0002 as a module so its _seed() is callable."""
    spec = importlib.util.spec_from_file_location(
        "migration_0002_user_management",
        _BACKEND_DIR / "alembic" / "versions" / "0002_user_management.py",
    )
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


async def test_seed_grants_admin_the_full_catalog_including_mcp(db, monkeypatch):
    """Fresh-database seed: admin holds every catalog code (mcp:* included),
    the baseline user role exists with no permissions, and the admin
    account is usable (no forced rotation)."""
    module = _load_migration()

    # Fixed password: the seed's generated-password banner is for humans
    # reading migration output, not for test logs.
    class _FixedSettings:
        initial_admin_password = "seed-test-password"

    monkeypatch.setattr(module, "get_settings", lambda: _FixedSettings())

    await asyncio.to_thread(_run_seed, module)

    codes = await _admin_permission_codes(db)
    assert len(codes) == len(set(codes)) == len(PERMISSION_CATALOG)
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
    assert admin.must_change_password is False
    assert admin.is_active is True


async def test_seed_is_rerunnable_without_duplicates(db, monkeypatch):
    """Re-running the seed on an already-seeded database is a no-op —
    the guards exist for downgrade/re-upgrade cycles and scripted
    re-seeds; this pins that behaviour."""
    module = _load_migration()

    class _FixedSettings:
        initial_admin_password = "seed-test-password"

    monkeypatch.setattr(module, "get_settings", lambda: _FixedSettings())

    await asyncio.to_thread(_run_seed, module)
    await asyncio.to_thread(_run_seed, module)

    codes = await _admin_permission_codes(db)
    assert len(codes) == len(PERMISSION_CATALOG)  # no duplicate grants
    users = (await db.execute(select(User).where(User.username == "admin"))).scalars().all()
    assert len(users) == 1
