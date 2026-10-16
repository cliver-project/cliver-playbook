"""Generic OIDC client login (the app as a relying party).

Flow (authorization code + PKCE, state in an HMAC-signed cookie):

    GET /auth/oauth/{provider}/login
      -> 302 IdP authorize URL + Set-Cookie state blob (HttpOnly)
    GET /auth/oauth/{provider}/callback?code=...&state=...
      -> verify cookie signature + state match
      -> exchange code (with code_verifier) at the token endpoint
      -> GET userinfo with the access token
      -> resolve (provider, sub) to a local user via oauth_identities,
         auto-provisioning when enabled
      -> issue a normal web token; 302 to the SPA with #token=...

Design choices:

- **userinfo identification, no id_token validation.** We never parse or verify
  the id_token JWT: the token came over TLS directly from the IdP's token
  endpoint in response to our one-time code + PKCE verifier, so the userinfo
  payload is at least as trustworthy as a locally-verified JWT would be, and
  we avoid a PyJWT/JWKS dependency plus key-rotation handling. This is the
  same trade the backend-for-frontend pattern usually makes.
- **One provider from flat settings, registry-shaped code.** `PROVIDERS` is a
  dict so extra providers can be registered without touching flow code.
- **Discovery cached 1h** per issuer — the document is static in practice, and
  this keeps the login path at two IdP round-trips (token + userinfo).
- The HTTP entry points accept an injected `httpx.AsyncClient` — tests drive
  the whole flow with `httpx.MockTransport` and zero network.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

_STATE_COOKIE = "cliver_oauth_state"
_STATE_TTL_SECONDS = 600
_DISCOVERY_TTL_SECONDS = 3600


@dataclass(frozen=True)
class ProviderConfig:
    """One registered external IdP."""

    key: str  # URL segment + oauth_identities.provider value
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    auto_provision: bool = True
    default_role: str = "user"


def build_provider_registry() -> dict[str, ProviderConfig]:
    """Registry from flat CLIVER_OIDC_* settings (single provider, 'default').

    Structured as a dict from day one: registering a second provider later is
    an additive change (env parsing here + a button in the UI), not a refactor.
    """
    settings = get_settings()
    if not (settings.oidc_enabled and settings.oidc_issuer and settings.oidc_client_id):
        return {}
    return {
        "default": ProviderConfig(
            key="default",
            issuer=settings.oidc_issuer.rstrip("/"),
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            scopes=settings.oidc_scopes,
            auto_provision=settings.oidc_auto_provision,
            default_role=settings.oidc_default_role,
        )
    }


# ---------------------------------------------------------------------------
# PKCE + state helpers
# ---------------------------------------------------------------------------


def make_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) — RFC 7636 S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def sign_state_blob(provider_key: str, state: str, code_verifier: str) -> str:
    """Serialize + HMAC-sign the state blob stored in the cookie.

    The verifier travels in the cookie (not the URL) so the browser redirect
    chain never exposes it; the signature stops a forged cookie from steering
    the callback at an attacker-chosen authorization.
    """
    secret = get_settings().hmac_secret
    payload = json.dumps(
        {
            "provider": provider_key,
            "state": state,
            "verifier": code_verifier,
            "exp": int(time.time()) + _STATE_TTL_SECONDS,
        },
        separators=(",", ":"),
    ).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload + b"." + sig.encode()).decode()


def verify_state_blob(blob: str, *, provider_key: str, state: str) -> str | None:
    """Validate signature, expiry, provider, and state echo.

    Returns the code_verifier on success, None on any mismatch — the caller
    turns None into a 400 without details (do not help an attacker debug).
    """
    secret = get_settings().hmac_secret
    try:
        raw = base64.urlsafe_b64decode(blob.encode())
        payload, sig_bytes = raw.rsplit(b".", 1)
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_bytes.decode(), expected):
            return None
        data = json.loads(payload)
        if data["exp"] < time.time():
            return None
        if data["provider"] != provider_key or not hmac.compare_digest(
            str(data["state"]), str(state)
        ):
            return None
        return str(data["verifier"])
    except (ValueError, KeyError, TypeError):
        return None


state_cookie_name = _STATE_COOKIE


# ---------------------------------------------------------------------------
# IdP HTTP calls
# ---------------------------------------------------------------------------


_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _open_client() -> httpx.AsyncClient:
    """Default outbound client. Tests swap this for MockTransport injection."""
    return httpx.AsyncClient(timeout=10.0)


async def discover(issuer: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Fetch (and cache) the issuer's openid-configuration document."""
    now = time.time()
    cached = _discovery_cache.get(issuer)
    if cached and cached[0] > now:
        return cached[1]

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    close = client is None
    if close:
        client = _open_client()
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        document = resp.json()
    finally:
        if close:
            await client.aclose()
    _discovery_cache[issuer] = (now + _DISCOVERY_TTL_SECONDS, document)
    return document


async def exchange_code(
    provider: ProviderConfig,
    discovery: dict[str, Any],
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange the one-time code for tokens at the IdP token endpoint."""
    close = client is None
    if close:
        client = _open_client()
    try:
        resp = await client.post(
            discovery["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if close:
            await client.aclose()


async def fetch_userinfo(
    discovery: dict[str, Any],
    access_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch the end-user claims from the userinfo endpoint."""
    close = client is None
    if close:
        client = _open_client()
    try:
        resp = await client.get(
            discovery["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if close:
            await client.aclose()


def build_authorize_url(
    provider: ProviderConfig,
    discovery: dict[str, Any],
    *,
    state: str,
    code_challenge: str,
    redirect_uri: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": provider.scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


async def find_linked_user(db: AsyncSession, provider_key: str, subject: str) -> int | None:
    """Local user id for an IdP identity, or None."""
    from app.models.entities import OauthIdentity

    row = (
        await db.execute(
            select(OauthIdentity.user_id).where(
                OauthIdentity.provider == provider_key,
                OauthIdentity.subject == subject,
            )
        )
    ).scalar_one_or_none()
    return row
