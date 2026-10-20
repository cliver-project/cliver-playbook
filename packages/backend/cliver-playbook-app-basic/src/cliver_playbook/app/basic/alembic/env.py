"""Alembic migration environment for the ``basic`` package.

Runs on the *sync* psycopg driver (see ``Settings.sync_db_url``) while the
application itself uses asyncpg. The two drivers never share an engine.

This environment serves exactly one chain: the revisions in ``versions/``
owned by this package, tracked in its own version table (``VERSION_TABLE``
below). Sibling packages own their own chains and tables, so several packages
can migrate the same database independently (ADR-0015). The chain is applied
programmatically through ``cliver_playbook.app.basic.alembic`` — the entry
point a new project calls at initialization — or interactively via the
bundled alembic.ini.

URL resolution: an explicit ``sqlalchemy.url`` already set on the Alembic
config (the programmatic entry points pass the deploy/test URL that way)
wins; otherwise the URL derives from the runtime settings — the instance
bound by ``runtime.configure`` when the application is running in-process,
else this package's own ``Settings()``. Either path goes through the
``settings`` proxy, so no config file is read while merely importing env.py.

Autogenerate support: ``target_metadata`` points at the package's ORM
declarative base so ``alembic revision --autogenerate`` diffs the real models.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cliver_playbook.app.basic.db.base import Base
from cliver_playbook.app.basic.models import entities  # noqa: F401 — imported for its table definitions
from cliver_playbook.app.basic.settings import settings

# Version table owned by THIS package's chain — never the default
# "alembic_version": sibling packages migrate the same database independently.
VERSION_TABLE = "alembic_version_basic"

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which silently disables every
    # logger that already exists when this env runs — fatal when migrations
    # run in-process (tests, scripted deploys) after the application's
    # loggers have been created. False keeps them emitting; alembic.ini
    # still owns the loggers it explicitly configures.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Explicit config override, else the current settings' sync DSN."""
    url = config.get_main_option("sqlalchemy.url")
    return url if url else settings.sync_db_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of touching a database."""
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
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
            target_metadata=Base.metadata,
            version_table=VERSION_TABLE,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
