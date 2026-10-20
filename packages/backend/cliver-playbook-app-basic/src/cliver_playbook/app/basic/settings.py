"""Application settings for the ``basic`` package — the extensibility root.

Single source of truth for configuration *structure*: the fields below define
what every cliver-playbook application configures; sibling packages subclass
``Settings`` to add their own fields (ADR-0016). Values come from a layered
resolution (highest precedence first):

    constructor kwargs > CLIVER_-prefixed environment > project .env
    > project app.yaml (Jinja2-rendered) > field defaults

The YAML layer (see config_yaml.py) is optional and checked in with
non-secret defaults; env/.env carry per-deployment values and secrets. The
``CLIVER_`` env prefix is a fixed convention — note that YAML keys are the
*bare field names*, without the prefix.

Import safety: nothing here reads configuration at import time. The
module-level ``settings`` is a lazy proxy that resolves to the
process-configured instance (``runtime.configure``, called by every
``create_app``) or, when the process was never configured, to this package's
own ``Settings()`` built on first attribute access (ADR-0016).

Database URL contract (ADR-0001):
- ``CLIVER_DATABASE_URL`` holds the *canonical* form ``postgresql://user:pass@host:port/db``.
- ``db_url`` derives the asyncpg DSN used by the application at runtime.
- ``sync_db_url`` derives the psycopg DSN used by Alembic only.
- The default matches the bundled docker-compose database, so a fresh
  checkout starts with zero configuration; real deployments override it.
  An explicitly-empty value still refuses to start — fail fast beats a
  cryptic connection error deep inside the first query.
"""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from cliver_playbook.app.basic.config_yaml import (
    JinjaYamlSource,
    resolve_config_path,
    resolve_env_file,
)
from cliver_playbook.app.basic.runtime import lazy_settings

# Matches the db service in docker-compose.yml (make db-up) — see class doc.
_DEFAULT_DATABASE_URL = "postgresql://cliver:cliver@127.0.0.1:5432/cliver_app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLIVER_",
        # Unknown env vars are ignored on purpose: the shell carries plenty of
        # non-Settings CLIVER_* helpers (e.g. CLIVER_TEST_DATABASE_URL for the
        # test bootstrap), and BaseSettings' default `forbid` would reject them.
        extra="ignore",
        # "__" separates nesting levels when an env var overrides a composite
        # field, e.g. CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET (used by
        # the user-management package's provider registry). Dict keys that
        # arrive through env are lowercased by pydantic-settings.
        env_nested_delimiter="__",
    )

    def __init__(self, **values: Any) -> None:
        """Resolve the .env layer dynamically, unless the caller overrode it.

        An installed package has no fixed relationship to the project
        consuming it, so the .env location is discovered per instantiation by
        walking up from the current working directory (see
        ``resolve_env_file``) — a path frozen into ``model_config`` or derived
        from ``__file__`` would point into site-packages.

        An explicit ``_env_file`` kwarg always wins: tests point it at a temp
        file for hermeticity, and ``_env_file=None`` disables the layer
        entirely — both are stock pydantic-settings semantics.
        """
        if "_env_file" not in values:
            values["_env_file"] = resolve_env_file()
        super().__init__(**values)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Layered precedence: env > .env > app.yaml > field defaults.

        Tuple order IS precedence (first source holding a value wins). The
        YAML layer is appended last as the Jinja2-rendered source; the stock
        `file_secret_settings` (secrets_dir mechanism) is dropped — this stack
        keeps secrets in the environment, not in a secrets directory.

        The config-file path resolves per instantiation (not once at class
        creation) so tests can point $CLIVER_CONFIG_FILE at a temp file and
        construct a fresh Settings() directly.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            JinjaYamlSource(settings_cls, yaml_file=resolve_config_path()),
        )

    # Canonical PostgreSQL URL. Default = the bundled compose db (zero-config
    # local development); override for any other environment.
    database_url: str = _DEFAULT_DATABASE_URL

    # Display name: FastAPI title and frontend branding.
    app_name: str = "cliver-app"

    log_level: str = "INFO"

    # Note: there is deliberately no API-prefix field. Routers own static
    # prefixes (see api/routes.py) — an APIRouter's prefix is fixed at import
    # time, so a settings-driven prefix would freeze whichever Settings
    # instance happened to load first while making the URL surface invisible
    # in the route table.

    def _require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "CLIVER_DATABASE_URL is set to an empty value. "
                "Point it at your PostgreSQL instance, or run `make db-up` "
                "to start the bundled container and keep the default."
            )
        return self.database_url

    @property
    def db_url(self) -> str:
        """Async DSN (asyncpg driver) for application runtime."""
        return (
            self._require_database_url()
            .replace("postgresql://", "postgresql+asyncpg://", 1)
            .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        )

    @property
    def sync_db_url(self) -> str:
        """Sync DSN (psycopg driver) for Alembic. Never share engines across drivers."""
        return (
            self._require_database_url()
            .replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            .replace("postgresql://", "postgresql+psycopg://", 1)
        )


# Process-aware lazy proxy: resolves to the runtime-bound instance (any
# package's Settings subclass) or to a lazily built Settings() of this class.
settings = lazy_settings(Settings)


def get_settings() -> Settings:
    """Return the process-wide Settings instance (see ``settings`` above).

    Kept as a function for call sites written against the previous
    accessor: returns the runtime-bound instance when the process is
    configured, else this package's own lazily-built ``Settings()``.
    """
    return settings.resolve()
