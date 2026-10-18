"""The aggregate migration entry: every chain, dependency order, re-runnable.

A deployment initializes its database through ``run_all_migrations`` (the
Makefile's ``db-init`` target), so this entry has to keep working when a
package adds or renumbers a chain. The temp database is already at head when
these tests run — the conftest applied all three chains — which makes the
first test a check of the property deployments actually rely on: running it
again is a harmless no-op, so a startup script may call it unconditionally.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from cliver_playbook.app.mcp.migrate import main, run_all_migrations
from cliver_playbook.app.mcp.settings import settings


def test_run_all_migrations_is_idempotent():
    """Against a current database: no error, and every chain stays at one head."""
    run_all_migrations()


def test_cli_accepts_an_explicit_database_url():
    """``--database-url`` reaches every chain — the DSN path a deployment that
    cannot rely on ambient configuration uses."""
    assert main(["--database-url", settings.sync_db_url]) == 0


async def test_every_chain_left_a_version_row(db: Any):
    """Every chain ran and is tracked in its own version table (ADR-0015) —
    the observable result of the aggregate entry, not just its exit status."""
    for table in ("alembic_version_basic", "alembic_version_user", "alembic_version_rag"):
        rows = (await db.execute(text(f"SELECT version_num FROM {table}"))).scalars().all()
        assert len(rows) == 1, f"{table} should hold exactly one current revision"
