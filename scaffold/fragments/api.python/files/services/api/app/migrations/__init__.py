"""Project-owned Alembic chain with its own version table."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_SCRIPT_LOCATION = Path(__file__).resolve().parent


def run_migrations_online(database_url: str | None = None) -> None:
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
