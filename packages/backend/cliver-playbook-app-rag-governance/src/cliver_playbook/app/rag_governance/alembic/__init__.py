"""Programmatic migration entry points for the ``rag_governance`` package.

Mirrors every sibling package: a project initializes its database by
calling each package's ``run_migrations_online`` in dependency order.
The interactive CLI (`alembic upgrade head` from this package's root)
shares the same env.py and version table.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_SCRIPT_LOCATION = Path(__file__).resolve().parent


def make_config(database_url: str | None = None) -> Config:
    """Build an Alembic config for this package's chain."""
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations_online(database_url: str | None = None) -> None:
    """Upgrade this package's chain to head against a live database."""
    command.upgrade(make_config(database_url), "head")


def run_migrations_offline(database_url: str | None = None) -> None:
    """Print the equivalent upgrade SQL to stdout without connecting."""
    command.upgrade(make_config(database_url), "head", sql=True)


__all__ = ["run_migrations_offline", "run_migrations_online"]
