"""Alembic migration environment for the ``rag_governance`` package.

Same shape as the rag environment: the sync psycopg driver runs the
migrations while the application uses asyncpg, and this package owns a
single chain tracked in ``alembic_version_rag_governance`` so sibling
packages migrate the same database independently (ADR-0015).

No governance table has a foreign key into ``rag_*``; the chain can be
applied to a database where the rag chain has not run yet. Application
startup still applies rag first because governance queries rag tables.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cliver_playbook.app.rag_governance.models import (
    GovernanceBase,
    entities,  # noqa: F401
)
from cliver_playbook.app.rag_governance.settings import settings

# Version table owned by THIS package's chain.
VERSION_TABLE = "alembic_version_rag_governance"

config = context.config

if config.config_file_name is not None:
    # Keep the application's existing loggers alive when migrations run
    # in-process (tests, scripted deploys).
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Explicit config override, else the current settings' sync DSN."""
    url = config.get_main_option("sqlalchemy.url")
    return url if url else settings.sync_db_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of touching a database."""
    context.configure(
        url=_database_url(),
        target_metadata=GovernanceBase.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=GovernanceBase.metadata,
            version_table=VERSION_TABLE,
        )

        with context.begin_transaction():
            context.run_migrations()


# env.py is executed as a script by Alembic; without this dispatch the
# file defines the functions and exits, and `upgrade head` silently
# creates nothing.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
