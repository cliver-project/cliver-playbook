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
- The default matches the bundled docker-compose database (zero-config dev);
  an explicitly-empty value refuses to start — fail fast beats a cryptic
  connection error deep inside the first query.

Identity-domain settings (this template's additions over the scaffold):
- `secret_key` signs short-lived HMAC blobs (OIDC state, OAuth login tickets).
- `initial_admin_password` is read by the migration seed only.
- `oidc` is the external-IdP registry this app trusts for login and account
  linking (ADR-0005 keeps us a *client* of some IdP; the app is an OIDC
  relying party). One nested entry per provider under `oidc.providers.<key>`;
  env overrides use the "__" delimiter, e.g.
  CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET.
- `oauth21_*` configures the OAuth 2.1 *provider* side for AI-agent clients.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from app.core.config_yaml import JinjaYamlSource, resolve_config_path

# The .env file lives at the PROJECT ROOT (next to the Makefile and
# docker-compose.yml). Anchoring it to this module's location instead of the
# process CWD keeps behavior identical whether uvicorn starts from the root
# or from backend/ — the Makefile does the latter, and a CWD-relative ".env"
# would silently miss the root file. Depth: <root>/backend/app/core/config.py.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Matches the db service in docker-compose.yml (make db-up) — zero-config
# local development; real deployments override via env or .env.
_DEFAULT_DATABASE_URL = "postgresql://cliver:cliver@127.0.0.1:5432/cliver_app"

# Provider registry keys double as URL path segments
# (/api/v1/auth/oauth/<key>/login|callback) and as oauth_identities.provider
# column values (String(32)) — keep them to a conservative, stable charset.
_PROVIDER_KEY_PATTERN = r"[a-z][a-z0-9_-]{0,31}"
_PROVIDER_KEY_RE = re.compile(f"^{_PROVIDER_KEY_PATTERN}$")

# Keys that would collide with the fixed sibling routes under
# /api/v1/auth/oauth/ (the providers listing, the OAuth 2.1 authorize
# hand-off). Rejected prophylactically: a provider segment and a fixed-route
# segment are indistinguishable in the URL space.
_RESERVED_PROVIDER_KEYS = frozenset({"providers", "authorize", "callback", "login"})


class OidcProviderSettings(BaseModel):
    """One external identity provider (login + profile account linking).

    Two endpoint shapes, complementary:
    - discovery: `issuer` set -> the three endpoints come from the standard
      /.well-known/openid-configuration document (cached 1h);
    - explicit: `authorize_url`/`token_url`/`userinfo_url` set -> for OAuth2
      services without discovery (e.g. GitHub).

    `subject_claim` names the userinfo field carrying the provider-side
    stable user id: "sub" for standard OIDC, "id" for GitHub-style APIs
    returning a numeric account id.

    Defaults keep disabled/empty presets harmless: the bundled app.yaml ships
    provider presets with `enabled: false`, and the credential/endpoint
    validation only fires once a provider is actually enabled.
    """

    enabled: bool = False
    # Button text in the login/profile UI; empty -> key.title() at the edge.
    label: str = ""
    client_id: str = ""
    client_secret: str = ""
    issuer: str = ""
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    # Space-separated string (what the IdP authorize URL expects on the wire).
    scopes: str = "openid profile email"
    subject_claim: str = "sub"
    # Auto-create a local account on first login of an unknown identity.
    auto_provision: bool = True
    default_role: str = "user"

    @field_validator("scopes", mode="before")
    @classmethod
    def _join_scopes(cls, value: Any) -> Any:
        # YAML authors naturally write scopes as a list, but the field must
        # stay `str`: the env layer JSON-parses complex-typed fields, so a
        # `list[str]` annotation would reject the plain space-separated
        # CLIVER_OIDC__...__SCOPES form. Accept both shapes here instead.
        if isinstance(value, (list, tuple)):
            return " ".join(str(v) for v in value)
        return value

    @model_validator(mode="after")
    def _check_credentials_and_endpoints(self) -> "OidcProviderSettings":
        # Fail at startup, not at first login: an enabled provider without
        # credentials or endpoints can never complete a flow. The pydantic
        # ValidationError carries the providers.<key> path, naming the culprit.
        if not self.enabled:
            return self
        missing = [
            name
            for name, value in (
                ("client_id", self.client_id),
                ("client_secret", self.client_secret),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"enabled provider is missing {', '.join(missing)}")
        if not self.issuer and not (self.authorize_url and self.token_url and self.userinfo_url):
            raise ValueError(
                "enabled provider needs either `issuer` (OIDC discovery) or all of "
                "authorize_url/token_url/userinfo_url (explicit endpoints)"
            )
        return self


class OidcSettings(BaseModel):
    """OIDC client block: shared redirect base + the provider registry."""

    # Absolute base URL of THIS backend as the IdP sees it, for building the
    # redirect_uri (must be registered with the IdP). Empty -> derived from
    # the incoming request; set it when running behind a proxy that rewrites
    # Host.
    redirect_base: str = ""  # e.g. http://127.0.0.1:8000
    providers: dict[str, OidcProviderSettings] = Field(default_factory=dict)

    @field_validator("providers", mode="before")
    @classmethod
    def _lowercase_keys(cls, value: Any) -> Any:
        # Env-sourced dict keys are lowercased by pydantic-settings while
        # YAML preserves author casing, and the cross-source merge happens
        # on RAW dicts BEFORE field validation — so a yaml `Google:` entry
        # plus a CLIVER_OIDC__PROVIDERS__GOOGLE__* env override arrive here
        # as two sibling keys. Fold them onto one lowercase key, merging
        # entry dicts. Later siblings win scalar conflicts, which matches
        # source precedence: the settings merger uses each lower-priority
        # source as the base, so iteration order here is lowest-priority
        # first (yaml, then .env, then environment, then init kwargs).
        if not isinstance(value, dict):
            return value
        merged: dict[str, Any] = {}
        for key, entry in value.items():
            low = str(key).lower()
            current = merged.get(low)
            if isinstance(current, dict) and isinstance(entry, dict):
                merged[low] = {**current, **entry}
            else:
                merged[low] = entry
        return merged

    @model_validator(mode="after")
    def _check_keys(self) -> "OidcSettings":
        for key in self.providers:
            if not _PROVIDER_KEY_RE.match(key):
                raise ValueError(
                    f"provider key {key!r} is invalid: must match {_PROVIDER_KEY_PATTERN} "
                    "(it becomes a URL path segment and a database column value)"
                )
            if key in _RESERVED_PROVIDER_KEYS:
                raise ValueError(
                    f"provider key {key!r} is reserved (collides with the fixed auth routes)"
                )
        return self


class McpOauthSettings(BaseModel):
    """OAuth 2.1 issuer knobs for the MCP-mounted authorization server.

    Kept separate from the Web's oauth21_* block: the MCP surface may run
    standalone (different origin/port), so its issuer and TTLs can differ
    from the Web's. TTL defaults mirror the Web's values.
    """

    # AS metadata base; empty = derived per-request from Host/protocol.
    issuer_url: str = ""
    access_ttl_seconds: int = 3600
    refresh_ttl_seconds: int = 30 * 86400
    code_ttl_seconds: int = 300


class McpSettings(BaseModel):
    """MCP server block (see app.yaml's `mcp:` section for the narrative)."""

    # Auth gate flag. Default OFF: local development / trusted networks.
    # ON = every request must carry a bearer token from the shared
    # auth_tokens table (same issuance/revocation path as the Web's).
    auth_enabled: bool = False

    # Public path of the MCP endpoint on the parent app. Must start with
    # "/" and not end with "/" — it becomes the SDK route path (exact-match,
    # no trailing-slash redirect).
    mount_path: str = "/mcp"

    # Process-wide cap on concurrently executing MCP tool calls (a
    # semaphore in app/mcp/toolkit.py). Queueing, not rejection; values
    # below 1 are clamped to 1 at use.
    max_concurrent_calls: int = 16

    # Agent self-identification: values outside the whitelist normalise to
    # "unknown" in audit rows. Empty list = accept any string (dev default).
    agent_type_whitelist: list[str] = Field(
        default_factory=lambda: ["claude-code", "workbuddy", "codex", "mcp-cli", "unknown"]
    )

    # Agent ids are stored verbatim up to this length, truncated beyond.
    agent_id_max_length: int = 128

    oauth: McpOauthSettings = Field(default_factory=McpOauthSettings)

    @field_validator("mount_path")
    @classmethod
    def _validate_mount_path(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/") or len(value) < 2:
            raise ValueError(
                "mcp.mount_path must start with '/' and not end with '/' "
                f"(got {value!r}) — it is the SDK route path, exact-match"
            )
        return value


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

    # --- OIDC client (login via external identity providers) ---
    # Nested registry: one entry per provider under `oidc.providers.<key>`.
    # Empty/disabled by default -> the login page shows no SSO buttons.
    # Env override form uses the "__" nesting delimiter, e.g.
    # CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET=... (dict keys arriving
    # through env are lowercased; the model lowercases YAML keys to match).
    oidc: OidcSettings = Field(default_factory=OidcSettings)

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

    # ------------------------------------------------------------------
    # MCP server (this template's delta over user-management)
    # ------------------------------------------------------------------

    # Nested block; env overrides use CLIVER_MCP__* (double underscore),
    # yaml uses the `mcp:` mapping — same rules as the oidc block.
    mcp: McpSettings = Field(default_factory=McpSettings)

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
