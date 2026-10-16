"""Alembic migration environment.

Runs on the *sync* psycopg driver (see config.py `sync_db_url`) while the
application itself uses asyncpg. The two drivers never share an engine.

Autogenerate support: `target_metadata` points at the application's ORM
declarative base so `alembic revision --autogenerate` diffs the real models.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings
from app.db.base import Base
from app.models import entities  # noqa: F401 — imported for its table definitions

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which silently disables every
    # logger that already exists when this env runs — fatal when migrations
    # run in-process (tests, scripted deploys) after the application's
    # loggers have been created. False keeps them emitting; alembic.ini
    # still owns the loggers it explicitly configures.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Single source of truth: canonical URL -> sync (psycopg) DSN.
config.set_main_option("sqlalchemy.url", settings.sync_db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of touching a database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
