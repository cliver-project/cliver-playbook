"""Application settings for the ``user`` package — the identity domain.

Extends ``basic.Settings`` (``database_url``/``app_name``/``log_level`` plus
the layered resolution machinery) with the fields the identity domain needs:
password-login policy, OIDC client registry, OAuth 2.1 provider knobs, and
frontend hand-off URLs. The full layered resolution documented in
``basic.settings`` applies unchanged — the YAML/env keys below are just more
bare field names at the same layers, and a composed application's
``create_app`` binds this most-derived instance to the process runtime, which
every package's ``settings`` proxy then serves (ADR-0016).

Database URL contract (ADR-0001): ``db_url`` (asyncpg) for the application,
``sync_db_url`` (psycopg) for Alembic only — both inherited from ``basic``.

Identity-domain settings:
- ``secret_key`` signs short-lived HMAC blobs (OIDC state, OAuth login tickets).
- ``initial_admin_password`` is read by the migration seed only.
- ``oidc`` is the external-IdP registry this app trusts for login and account
  linking (ADR-0005 keeps us a *client* of some IdP; the app is an OIDC
  relying party). One nested entry per provider under ``oidc.providers.<key>``;
  env overrides use the "__" delimiter, e.g.
  CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET.
- ``oauth21_*`` configures the OAuth 2.1 *provider* side for AI-agent clients.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from cliver_playbook.app.basic.runtime import lazy_settings
from cliver_playbook.app.basic.settings import Settings as BasicSettings

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
    def _check_credentials_and_endpoints(self) -> OidcProviderSettings:
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
    def _check_keys(self) -> OidcSettings:
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


class Settings(BasicSettings):
    """Identity-domain settings on top of the ``basic`` layer.

    Every ``basic`` field and behaviour is inherited — including the dynamic
    .env discovery and the ``settings_customise_sources`` layer order — so a
    composed application resolves one configuration for the whole process.
    """

    # HMAC key for signed blobs (OIDC state cookies, OAuth login tickets).
    # Empty -> derived deterministically from database_url (zero-config dev;
    # rotating the database URL invalidates outstanding blobs, which is fine).
    secret_key: str = ""

    # Read by the migration seed. Empty -> a random password is generated and
    # printed once; first login forces a change either way.
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


# Process-aware lazy proxy (see basic.runtime.lazy_settings): resolves to the
# runtime-bound instance — this class, a subclass, or any composed application's
# Settings — or to a lazily built Settings() of this class when unconfigured.
settings = lazy_settings(Settings)


def get_settings() -> Settings:
    """Return the process-wide Settings instance (see ``settings`` above)."""
    return settings.resolve()
