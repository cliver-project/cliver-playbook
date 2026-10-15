"""Application settings.

Single source of truth for configuration: every variable uses the `CLIVER_`
env prefix (the project-rename surface — see ADR-0002) and is loaded from the
environment plus an optional `.env` file at the project root.

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

from pydantic_settings import BaseSettings, SettingsConfigDict

# The .env file lives at the PROJECT ROOT (next to the Makefile and
# docker-compose.yml). Anchoring it to this module's location instead of the
# process CWD keeps behavior identical whether uvicorn starts from the root
# or from backend/ — the Makefile does the latter, and a CWD-relative ".env"
# would silently miss the root file. Depth: <root>/backend/app/core/config.py.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Matches the db service in docker-compose.yml (make db-up) — see class doc.
_DEFAULT_DATABASE_URL = "postgresql://cliver:cliver@127.0.0.1:5432/cliver_app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="CLIVER_", extra="ignore")

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
