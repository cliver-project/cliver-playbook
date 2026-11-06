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
- **Registry-shaped, settings-driven.** The provider registry is built from
  the nested `oidc.providers` settings block; adding an identity provider is
  a configuration change. Each provider is discovery-based (`issuer`),
  explicit-endpoint (`authorize_url` / `token_url` / `userinfo_url`, for OAuth2
  services with no discovery document), or adapter-backed (`adapter`, for
  non-OAuth2 protocols — built-ins: `wechat`, `alipay`; projects may register
  their own, ADR-0024). `endpoints_for` normalizes the first two into one
  discovery-shaped dict; an adapter owns both the authorize URL and the
  code-for-identity exchange (`build_authorize_redirect` / `complete_login`).
- **Discovery cached 1h** per issuer — the document is static in practice, and
  this keeps the login path at two IdP round-trips (token + userinfo).
- The HTTP entry points accept an injected `httpx.AsyncClient` — tests drive
  the whole flow with `httpx.MockTransport` and zero network.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.user.auth.adapters import adapter_names, get_adapter
from cliver_playbook.app.user.auth.provider import Identity, ProviderConfig
from cliver_playbook.app.user.settings import get_settings

_STATE_COOKIE = "cliver_oauth_state"
_STATE_TTL_SECONDS = 600
_DISCOVERY_TTL_SECONDS = 3600


def build_provider_registry() -> dict[str, ProviderConfig]:
    """Registry from the nested `oidc.providers` settings block.

    Only enabled providers are registered: a disabled preset (the bundled
    app.yaml ships google/github that way) contributes nothing, and the login
    page hides its button. Keys are validated by the settings model
    (charset + reserved words), so they are safe as URL path segments and as
    oauth_identities.provider column values.
    """
    settings = get_settings()
    available_adapters = adapter_names()
    registry: dict[str, ProviderConfig] = {}
    for key, provider in settings.oidc.providers.items():
        if not provider.enabled:
            continue
        if provider.adapter and provider.adapter not in available_adapters:
            raise ValueError(
                f"provider {key!r} uses unknown adapter {provider.adapter!r}; "
                f"registered adapters: {', '.join(sorted(available_adapters)) or '(none)'}"
            )
        registry[key] = ProviderConfig(
            key=key,
            issuer=provider.issuer.rstrip("/"),
            client_id=provider.client_id,
            client_secret=provider.client_secret,
            scopes=provider.scopes,
            auto_provision=provider.auto_provision,
            default_role=provider.default_role,
            label=provider.label,
            subject_claim=provider.subject_claim,
            authorize_url=provider.authorize_url,
            token_url=provider.token_url,
            userinfo_url=provider.userinfo_url,
            adapter=provider.adapter,
        )
    return registry


# ---------------------------------------------------------------------------
# PKCE + state helpers
# ---------------------------------------------------------------------------


def make_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) — RFC 7636 S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def sign_state_blob(
    provider_key: str,
    state: str,
    code_verifier: str,
    *,
    mode: str = "login",
    user_id: int | None = None,
) -> str:
    """Serialize + HMAC-sign the state blob stored in the cookie.

    The verifier travels in the cookie (not the URL) so the browser redirect
    chain never exposes it; the signature stops a forged cookie from steering
    the callback at an attacker-chosen authorization. `mode` distinguishes a
    login flow from an account-linking flow — "link" additionally pins the
    user_id the callback may attach the identity to, since the linking user
    is authenticated by their session token at link START, not at callback.
    """
    secret = get_settings().hmac_secret
    payload = json.dumps(
        {
            "provider": provider_key,
            "state": state,
            "verifier": code_verifier,
            "mode": mode,
            # Present only for link blobs; login blobs stay lean.
            **({"user_id": user_id} if user_id is not None else {}),
            "exp": int(time.time()) + _STATE_TTL_SECONDS,
        },
        separators=(",", ":"),
    ).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload + b"." + sig.encode()).decode()


def verify_state_blob(blob: str, *, provider_key: str, state: str) -> dict[str, Any] | None:
    """Validate signature, expiry, provider, and state echo.

    Returns the verified payload dict on success, None on any mismatch — the
    caller turns None into a failure redirect without details (do not help an
    attacker debug). Blobs signed before the `mode` field existed (cookies in
    flight across a deploy) verify as mode="login", preserving compatibility.
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
        data.setdefault("mode", "login")
        return data
    except (ValueError, KeyError, TypeError):
        return None


_COOKIE_SUFFIX_RE = re.compile(r"[^a-z0-9_-]")


def state_cookie_name_for(provider_key: str) -> str:
    """One state cookie per provider, so concurrent logins cannot collide.

    With a single shared name, starting a login in a second tab overwrites
    the first tab's signed state blob and the first callback fails with
    ``state_mismatch``. Configured keys already match the cookie-safe
    charset; the callback path segment is attacker-controlled, so sanitize
    defensively rather than letting Starlette raise ``CookieError``.
    """
    suffix = _COOKIE_SUFFIX_RE.sub("_", provider_key.lower())[:32]
    return f"{_STATE_COOKIE}_{suffix or 'unknown'}"


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


async def endpoints_for(
    config: ProviderConfig, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """The provider's three flow endpoints as a discovery-shaped dict.

    Discovery-based providers fetch (and 1h-cache) the issuer's standard
    document; explicit-endpoint providers get a synthesized document with
    the same three keys. Everything downstream (build_authorize_url /
    exchange_code / fetch_userinfo) only reads those keys, so both shapes
    share one flow implementation. The settings model guarantees an enabled
    provider has either an issuer or all three explicit URLs.
    """
    if config.issuer:
        return await discover(config.issuer, client=client)
    return {
        "authorization_endpoint": config.authorize_url,
        "token_endpoint": config.token_url,
        "userinfo_endpoint": config.userinfo_url,
    }


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


async def build_authorize_redirect(
    config: ProviderConfig,
    *,
    state: str,
    code_challenge: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    """The provider's authorize URL, whichever protocol it speaks.

    Adapter-backed providers build the URL synchronously (no discovery call);
    standard providers resolve their endpoints and use the OAuth2 shape.
    """
    if config.adapter:
        return get_adapter(config.adapter).authorize_url(
            config,
            state=state,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
        )
    discovery = await endpoints_for(config, client=client)
    return build_authorize_url(
        config,
        discovery,
        state=state,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
    )


async def complete_login(
    config: ProviderConfig,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> Identity:
    """Exchange the one-time code for the provider-verified identity.

    Adapter-backed providers perform the whole exchange inside the adapter, so
    the upstream access token never reaches this module. The standard path
    keeps the existing two-call flow (token + userinfo) and wraps the userinfo
    payload in the same ``Identity`` shape, letting account linking and
    provisioning depend on one contract.
    """
    close = client is None
    if close:
        client = _open_client()
    try:
        if config.adapter:
            identity = await get_adapter(config.adapter).complete(
                config,
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
                client=client,
            )
            # The identity column is String(255); truncate once here so the
            # lookup and the stored subject always byte-match.
            return Identity(
                subject=str(identity.subject or "")[:255],
                claims=identity.claims,
            )

        discovery = await endpoints_for(config, client=client)
        token_response = await exchange_code(
            config,
            discovery,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            client=client,
        )
        if not isinstance(token_response, dict):
            raise TypeError("token response is not a JSON object")
        access_token = str(token_response.get("access_token", "") or "")
        userinfo = await fetch_userinfo(discovery, access_token, client=client)
        if not isinstance(userinfo, dict):
            raise TypeError("userinfo response is not a JSON object")
        subject = str(userinfo.get(config.subject_claim, "") or "")[:255]
        return Identity(subject=subject, claims=userinfo)
    finally:
        if close:
            await client.aclose()


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


async def find_linked_user(db: AsyncSession, provider_key: str, subject: str) -> int | None:
    """Local user id for an IdP identity, or None."""
    from cliver_playbook.app.user.models.entities import OauthIdentity

    row = (
        await db.execute(
            select(OauthIdentity.user_id).where(
                OauthIdentity.provider == provider_key,
                OauthIdentity.subject == subject,
            )
        )
    ).scalar_one_or_none()
    return row
