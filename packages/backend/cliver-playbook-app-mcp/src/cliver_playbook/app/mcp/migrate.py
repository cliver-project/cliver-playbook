"""Initialize the whole database: every dependency's chain, in order.

A composed project has one database and several migration chains, one per
package that owns tables (ADR-0015). Order matters — the identity tables carry
foreign keys into the basic package's tables — and the order is exactly the
dependency order of the packages, so this module is the single place that
knows it. Entry points for whoever sets up a deployment::

    python -m cliver_playbook.app.mcp.migrate     # the Makefile's db-init target
    from cliver_playbook.app.mcp.migrate import run_all_migrations

This package owns no tables and no chain of its own, so it is the natural home
for the aggregate entry: it is the top of the composition.

Each chain is tracked in its own version table, so re-running is a no-op once
the database is current — safe to call from a startup script.
"""

from __future__ import annotations

import sys


def run_all_migrations(database_url: str | None = None) -> None:
    """Upgrade every package's chain to head, dependencies first.

    Args:
        database_url: sync (psycopg) DSN to migrate. When omitted, each chain
            resolves it from the process settings (see the packages' env.py).
    """
    from cliver_playbook.app.basic.alembic import run_migrations_online as run_basic_migrations
    from cliver_playbook.app.rag.alembic import run_migrations_online as run_rag_migrations
    from cliver_playbook.app.user.alembic import run_migrations_online as run_user_migrations

    # Dependency order: identity tables reference basic's, and the rag
    # chain creates the vector extension the embedding table needs.
    run_basic_migrations(database_url)
    run_user_migrations(database_url)
    run_rag_migrations(database_url)


def main(argv: list[str] | None = None) -> int:
    """``python -m cliver_playbook.app.mcp.migrate [--database-url DSN]``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m cliver_playbook.app.mcp.migrate",
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
