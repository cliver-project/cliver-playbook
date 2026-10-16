"""Application settings.

Single source of truth for configuration: every variable uses the `CLIVER_`
env prefix (the project-rename surface — see ADR-0002) and is loaded from the
environment plus an optional `.env` file.

Database URL contract (ADR-0001):
- `CLIVER_DATABASE_URL` holds the *canonical* form `postgresql://user:pass@host:port/db`.
- `db_url` derives the asyncpg DSN used by the application at runtime.
- `sync_db_url` derives the psycopg DSN used by Alembic only.
- The default matches the bundled docker-compose database (zero-config dev);
  an explicitly-empty value refuses to start — fail fast beats a cryptic
  connection error deep inside the first query.

Identity-domain settings (this template's additions over the scaffold):
- `secret_key` signs short-lived HMAC blobs (OIDC state, OAuth login tickets).
- `initial_admin_password` is read by the migration seed only.
- `oidc_*` configures the external IdP this app trusts for login (ADR-0005
  keeps us a *client* of some IdP; the app is an OIDC relying party).
- `oauth21_*` configures the OAuth 2.1 *provider* side for AI-agent clients.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The .env file lives at the PROJECT ROOT (next to the Makefile and
# docker-compose.yml). Anchoring it to this module's location instead of the
# process CWD keeps behavior identical whether uvicorn starts from the root
# or from backend/ — the Makefile does the latter, and a CWD-relative ".env"
# would silently miss the root file. Depth: <root>/backend/app/core/config.py.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Matches the db service in docker-compose.yml (make db-up) — zero-config
# local development; real deployments override via env or .env.
_DEFAULT_DATABASE_URL = "postgresql://cliver:cliver@127.0.0.1:5432/cliver_app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="CLIVER_", extra="ignore")

    # Canonical PostgreSQL URL. Default = the bundled compose db; override
    # for any other environment. Explicitly-empty still refuses to start.
    database_url: str = _DEFAULT_DATABASE_URL

    # Display name: FastAPI title and frontend branding. Part of the rename surface.
    app_name: str = "cliver-app"

    log_level: str = "INFO"

    # API version prefix. Kept configurable so an existing deployment can pin
    # an older prefix during a transition.
    api_v1_prefix: str = "/api/v1"

    # ------------------------------------------------------------------
    # Identity domain (user-management template)
    # ------------------------------------------------------------------

    # HMAC key for signed blobs (OIDC state cookies, OAuth login tickets).
    # Empty -> derived deterministically from database_url (zero-config dev;
    # rotating the database URL invalidates outstanding blobs, which is fine).
    secret_key: str = ""

    # Read by the migration 0002 seed. Empty -> a random password is generated
    # and printed once; first login forces a change either way.
    initial_admin_password: str = ""

    # Web session tokens (days). Static and OAuth tokens have their own rules.
    token_ttl_days: int = 30

    # Brute-force lockout: N failed logins inside the window locks the account.
    login_lockout_threshold: int = 5
    login_lockout_minutes: int = 15

    # --- OIDC client (login via an external IdP) ---
    # Disabled by default: no IdP configured -> the login page just won't show SSO.
    oidc_enabled: bool = False
    oidc_issuer: str = ""  # e.g. https://accounts.example.com (discovery base)
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    # Auto-create a local account on first login of an unknown IdP identity.
    oidc_auto_provision: bool = True
    oidc_default_role: str = "user"
    # Absolute base URL of THIS backend as the IdP sees it, for building the
    # redirect_uri (must be registered with the IdP). Empty -> derived from the
    # incoming request; set it when running behind a proxy that rewrites Host.
    oidc_redirect_base: str = ""  # e.g. http://127.0.0.1:8000

    # --- Frontend ---
    # Where the SPA lives; the backend redirects there after OIDC login with
    # the session token in the URL fragment (fragments never reach server logs).
    web_base_url: str = "http://127.0.0.1:5173"

    # --- OAuth 2.1 provider (AI-agent / API clients, ADR-0005) ---
    # Toggle exists so a deployment without agent clients can switch the whole
    # provider surface off; static tokens (label rotation) remain available.
    oauth21_enabled: bool = True
    # External base URL of THIS service as agents reach it (the `iss` value).
    # Empty -> derived per-request from the incoming Host/protocol headers.
    # Set it explicitly whenever the service runs behind a proxy that rewrites
    # Host, because `iss` must match the URL the client used byte-for-byte.
    oauth21_issuer_url: str = ""
    # TTLs (seconds). Defaults follow RFC 9700 guidance: short access, long
    # one-time-rotating refresh, minutes for codes and login hand-off blobs.
    oauth21_access_ttl_seconds: int = 3600
    oauth21_refresh_ttl_seconds: int = 30 * 86400
    oauth21_code_ttl_seconds: int = 300
    oauth21_login_ttl_seconds: int = 600
    # Refresh-replay grace window: replays within it are audited as
    # race_suspected (network retries) instead of revoking the token family.
    oauth21_replay_grace_seconds: int = 30

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

    @property
    def hmac_secret(self) -> bytes:
        """Key material for HMAC-signed blobs. See `secret_key` for fallback rules."""
        if self.secret_key:
            return self.secret_key.encode()
        if self.database_url:
            return hashlib.sha256(f"cliver-hmac::{self.database_url}".encode()).digest()
        raise RuntimeError(
            "CLIVER_SECRET_KEY is not set (and no database URL to derive a key from). "
            "Set CLIVER_SECRET_KEY to a long random value."
        )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — tests override the cache after mutating env vars."""
    return Settings()


settings = get_settings()
