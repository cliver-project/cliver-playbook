"""Programmatic migration entry points for the ``rag`` package.

Every package owns its migration chain and exposes the same two
functions, so a project initializes its whole database by calling
each package's ``run_migrations_online`` in dependency order (basic
first, then the packages built on it) — no alembic.ini paths, no
working-directory assumptions.

The interactive CLI remains available for development: run
``alembic`` from the package directory, which picks up the bundled
alembic.ini. Both routes share ``alembic/env.py`` and therefore the
same version table.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

# env.py lives next to this module inside the installed package, so
# the script location is correct regardless of where the package is
# imported from.
_SCRIPT_LOCATION = Path(__file__).resolve().parent


def make_config(database_url: str | None = None) -> Config:
    """Build an Alembic config for this package's chain."""
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations_online(database_url: str | None = None) -> None:
    """Upgrade this package's chain to head against a live database.

    Args:
        database_url: sync (psycopg) DSN to migrate. When omitted, the
            process runtime's current settings decide (see
            alembic/env.py).
    """
    command.upgrade(make_config(database_url), "head")


def run_migrations_offline(database_url: str | None = None) -> None:
    """Print the equivalent upgrade SQL to stdout without connecting."""
    command.upgrade(make_config(database_url), "head", sql=True)


__all__ = ["run_migrations_offline", "run_migrations_online"]
