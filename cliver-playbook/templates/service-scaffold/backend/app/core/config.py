"""Application settings.

Single source of truth for configuration *structure*: the fields of the
Settings class below define what exists; the values come from a layered
resolution (highest precedence first):

    constructor kwargs > CLIVER_-prefixed environment > project-root .env
    > project-root app.yaml (Jinja2-rendered) > field defaults

The YAML layer (see app/core/config_yaml.py) is optional and checked in with
non-secret defaults; env/.env carry per-deployment values and secrets. The
`CLIVER_` env prefix is part of the project-rename surface (ADR-0002) — note
that YAML keys are the *bare field names*, without the prefix.

Database URL contract (ADR-0001):
- `CLIVER_DATABASE_URL` holds the *canonical* form `postgresql://user:pass@host:port/db`.
- `db_url` derives the asyncpg DSN used by the application at runtime.
- `sync_db_url` derives the psycopg DSN used by Alembic only.
- The default matches the bundled docker-compose database, so a fresh
  checkout starts with zero configuration; real deployments override it.
  An explicitly-empty value still refuses to start — fail fast beats a
  cryptic connection error deep inside the first query.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from app.core.config_yaml import JinjaYamlSource, resolve_config_path

# The .env file lives at the PROJECT ROOT (next to the Makefile and
# docker-compose.yml). Anchoring it to this module's location instead of the
# process CWD keeps behavior identical whether uvicorn starts from the root
# or from backend/ — the Makefile does the latter, and a CWD-relative ".env"
# would silently miss the root file. Depth: <root>/backend/app/core/config.py.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Matches the db service in docker-compose.yml (make db-up) — see class doc.
_DEFAULT_DATABASE_URL = "postgresql://cliver:cliver@127.0.0.1:5432/cliver_app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_prefix="CLIVER_",
        # Unknown env vars are ignored on purpose: the shell carries plenty of
        # non-Settings CLIVER_* helpers (e.g. CLIVER_TEST_DATABASE_URL for the
        # test bootstrap), and BaseSettings' default `forbid` would reject them.
        extra="ignore",
        # "__" separates nesting levels when an env var overrides a composite
        # field, e.g. CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET (used by
        # the user-management template's provider registry). Dict keys that
        # arrive through env are lowercased by pydantic-settings.
        env_nested_delimiter="__",
    )

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

    # Display name: FastAPI title and frontend branding. Part of the rename surface.
    app_name: str = "cliver-app"

    log_level: str = "INFO"

    # API version prefix. Kept configurable so an existing deployment can pin
    # an older prefix during a transition.
    api_v1_prefix: str = "/api/v1"

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


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — tests override the cache after mutating env vars."""
    return Settings()


settings = get_settings()
