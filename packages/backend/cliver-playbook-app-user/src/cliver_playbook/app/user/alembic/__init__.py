"""Programmatic migration entry points for the ``user`` package.

Every package owns its migration chain and exposes the same two functions, so
a project initializes its whole database by calling each package's
``run_migrations_online`` in dependency order — this chain depends on the
``basic`` package's tables via foreign keys, so its migrations run second::

    from cliver_playbook.app.basic.alembic import run_migrations_online
    from cliver_playbook.app.user.alembic import (
        run_migrations_online as run_user_migrations,
    )

    run_migrations_online(...)
    run_user_migrations(...)

Each chain is tracked in its own version table (see ``alembic/env.py``), so
the calls are independent of one another and of any sibling package's chain.

The interactive CLI remains available for development: run ``alembic`` from
the package directory, which picks up the bundled alembic.ini. Both routes
share ``alembic/env.py`` and therefore the same version table.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

# env.py lives next to this module inside the installed package, so the
# script location is correct regardless of where the package is imported from.
_SCRIPT_LOCATION = Path(__file__).resolve().parent


def make_config(database_url: str | None = None) -> Config:
    """Build an Alembic config for this package's chain.

    No ini file is involved: the script location is pinned to the installed
    package and the URL is passed through explicitly — omitted entirely when
    no URL is given, letting env.py fall back to application settings.
    Logging configuration is likewise untouched: in-process migrations must
    not reconfigure the host application's loggers.
    """
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations_online(database_url: str | None = None) -> None:
    """Upgrade this package's chain to head against a live database.

    Args:
        database_url: sync (psycopg) DSN to migrate. When omitted, the
            process runtime's current settings decide (see alembic/env.py).
    """
    command.upgrade(make_config(database_url), "head")


def run_migrations_offline(database_url: str | None = None) -> None:
    """Print the equivalent upgrade SQL to stdout without connecting.

    Offline mode still needs a URL (or settings) to render SQL for the right
    dialect; nothing is executed against a database.
    """
    command.upgrade(make_config(database_url), "head", sql=True)
