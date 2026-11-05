"""Initialize the whole database: every dependency's chain, in order.

Governance is the top of the composition it participates in, so this
module is the aggregate entry point for a deployment that installs it::

    python -m cliver_playbook.app.rag_governance.migrate
    from cliver_playbook.app.rag_governance.migrate import run_all_migrations

Each package owns its chain and its version table (ADR-0015), so
re-running is a no-op once the database is current. The order is the
package dependency order: basic, identity, rag (which creates the
pgvector extension), then governance.
"""

from __future__ import annotations

import sys


def run_all_migrations(database_url: str | None = None) -> None:
    """Upgrade every package's chain to head, dependencies first.

    Args:
        database_url: sync (psycopg) DSN to migrate. When omitted, each
            chain resolves it from the process settings.
    """
    from cliver_playbook.app.basic.alembic import run_migrations_online as run_basic_migrations
    from cliver_playbook.app.rag.alembic import run_migrations_online as run_rag_migrations
    from cliver_playbook.app.rag_governance.alembic import (
        run_migrations_online as run_governance_migrations,
    )
    from cliver_playbook.app.user.alembic import run_migrations_online as run_user_migrations

    run_basic_migrations(database_url)
    run_user_migrations(database_url)
    run_rag_migrations(database_url)
    run_governance_migrations(database_url)


def main(argv: list[str] | None = None) -> int:
    """``python -m cliver_playbook.app.rag_governance.migrate [--database-url DSN]``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m cliver_playbook.app.rag_governance.migrate",
        description="Apply every package's migration chain, dependencies first.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Sync (psycopg) DSN to migrate. Omit to use the configured "
            "database_url from app.yaml/.env/environment."
        ),
    )
    args = parser.parse_args(argv)

    run_all_migrations(args.database_url)
    return 0


if __name__ == "__main__":  # pragma: no cover — module entry point
    sys.exit(main())
