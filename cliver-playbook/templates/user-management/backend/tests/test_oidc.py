"""OIDC client login: provider listing, authorize redirect, full callback
flow, identity re-linking, auto-provision, state tampering, and both
provider endpoint shapes (discovery vs explicit).

The IdPs never exist — every outbound call (discovery, token, userinfo) is
served by an httpx.MockTransport installed through the `_open_client` seam,
so the whole flow runs with zero network. Two mock IdP shapes share one
transport, dispatched by request host:

- idp.example.com     — standards-shaped OIDC (discovery document, "sub");
- hub.example.com /
  api.hub.example.com — GitHub-style plain OAuth2: no discovery (explicit
                        authorize/token/userinfo URLs), a numeric int "id"
                        as the stable subject, and a nullable email.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.auth.oidc import ProviderConfig
from tests.helpers import seed_admin

ISSUER = "https://idp.example.com"
FRONTEND = "http://127.0.0.1:5173"
HUB_AUTHORIZE = "https://hub.example.com/login/oauth/authorize"
HUB_TOKEN = "https://hub.example.com/access_token"
HUB_USERINFO = "https://api.hub.example.com/user"
HUB_USER = {"id": 12345, "login": "hubuser", "email": None}


def _idp_handler(
    sub: str = "idp-user-1",
    email: str = "dev@example.com",
    hub_user: dict | None = None,
    token_response: httpx.Response | None = None,
):
    """Mock-IdP transport handler covering both provider shapes.

    `token_response` overrides the token-endpoint reply (on either host) to
    inject IdP failures; `hub_user` overrides the hub userinfo payload.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        ok_token = httpx.Response(200, json={"access_token": "at_test", "token_type": "Bearer"})
        if host == "idp.example.com":
            if path == "/.well-known/openid-configuration":
                return httpx.Response(
                    200,
                    json={
                        "issuer": ISSUER,
                        "authorization_endpoint": f"{ISSUER}/authorize",
                        "token_endpoint": f"{ISSUER}/token",
                        "userinfo_endpoint": f"{ISSUER}/userinfo",
                    },
                )
            if path == "/token":
                return token_response or ok_token
            if path == "/userinfo":
                return httpx.Response(
                    200,
                    json={
                        "sub": sub,
                        "email": email,
                        "name": "Dev User",
                        "phone_number": "+1-555-0100",
                    },
                )
            return httpx.Response(404)
        if host == "hub.example.com" and path == "/access_token":
            return token_response or ok_token
        if host == "api.hub.example.com" and path == "/user":
            return httpx.Response(200, json=HUB_USER if hub_user is None else hub_user)
        return httpx.Response(404)

    return handler


def _provider(auto_provision: bool = True) -> dict[str, ProviderConfig]:
    """A two-provider registry exercising both endpoint shapes."""
    return {
        "default": ProviderConfig(
            key="default",
            issuer=ISSUER,
            client_id="client-1",
            client_secret="secret-1",
            scopes="openid profile email",
            auto_provision=auto_provision,
            default_role="user",
        ),
        "mockhub": ProviderConfig(
            key="mockhub",
            issuer="",  # explicit endpoints: discovery must never be used
            client_id="hub-client",
            client_secret="hub-secret",
            scopes="read:user user:email",
            auto_provision=auto_provision,
            default_role="user",
            label="MockHub",
            subject_claim="id",
            authorize_url=HUB_AUTHORIZE,
            token_url=HUB_TOKEN,
            userinfo_url=HUB_USERINFO,
        ),
    }


@pytest.fixture
def idp(monkeypatch):
    """Mock IdP transport + a configured provider registry."""
    import app.api.auth as auth_api
    from app.auth import oidc

    monkeypatch.setattr(
        oidc,
        "_open_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_idp_handler())),
    )
    monkeypatch.setattr(auth_api, "build_provider_registry", _provider)
    # Per-test isolation from the module-level discovery cache.
    monkeypatch.setattr(oidc, "_discovery_cache", {})
    return oidc


def _frag_params(url: str) -> dict[str, str]:
    """Parse a redirect target's URL fragment into a dict."""
    parsed = urlparse(url)
    fragment = parse_qs(parsed.fragment)
    return {k: v[0] for k, v in fragment.items()}


def _no_discovery(monkeypatch, oidc_module):
    """Fail loudly if any code path attempts OIDC discovery."""

    async def spy(*args, **kwargs):
        raise AssertionError("discovery must not run for explicit-endpoint providers")

    monkeypatch.setattr(oidc_module, "discover", spy)


async def test_providers_endpoint_lists_configured(idp, client):
    resp = await client.get("/api/v1/auth/oauth/providers")
    assert resp.status_code == 200
    assert resp.json() == {
        "providers": [
            # Unset label -> title-cased key; configured label passes through.
            {"key": "default", "label": "Default"},
            {"key": "mockhub", "label": "MockHub"},
        ]
    }


async def test_login_redirect_shape(idp, client):
    resp = await client.get("/api/v1/auth/oauth/default/login")
    assert resp.status_code == 302
    target = urlparse(resp.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{ISSUER}/authorize"
    params = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert params["client_id"] == "client-1"
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    assert len(params["code_challenge"]) >= 43
    assert "state" in params
    # redirect_uri points at our callback on this backend (request-derived).
    assert params["redirect_uri"].endswith("/api/v1/auth/oauth/default/callback")
    # The state blob rides in an HttpOnly cookie.
    set_cookie = resp.headers["set-cookie"]
    assert "cliver_oauth_state=" in set_cookie and "HttpOnly" in set_cookie


async def test_explicit_login_skips_discovery(monkeypatch, idp, client):
    """Explicit-endpoint provider: login 302s to the configured authorize URL
    and never touches discovery."""
    _no_discovery(monkeypatch, idp)
    resp = await client.get("/api/v1/auth/oauth/mockhub/login")
    assert resp.status_code == 302
    target = urlparse(resp.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == HUB_AUTHORIZE
    params = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert params["client_id"] == "hub-client"
    assert params["scope"] == "read:user user:email"
    assert params["code_challenge_method"] == "S256"
    assert params["redirect_uri"].endswith("/api/v1/auth/oauth/mockhub/callback")


async def _run_callback(client, provider: str = "default") -> str:
    """Drive login -> callback with the IdP 'issuing' code xyz; returns the
    final redirect Location."""
    login = await client.get(f"/api/v1/auth/oauth/{provider}/login")
    state = {k: v[0] for k, v in parse_qs(urlparse(login.headers["location"]).query).items()}[
        "state"
    ]
    cookie = login.headers["set-cookie"].split(";")[0]
    callback = await client.get(
        f"/api/v1/auth/oauth/{provider}/callback",
        params={"code": "xyz", "state": state},
        headers={"Cookie": cookie},
    )
    return callback.headers["location"]


async def test_callback_full_flow_provisions_and_tokens(idp, client, db):
    from app.models.entities import User

    await seed_admin(db)
    location = await _run_callback(client)
    assert location.startswith(f"{FRONTEND}/auth/callback#")
    frag = _frag_params(location)
    assert frag["token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {frag['token']}"})
    assert me.status_code == 200
    username = me.json()["user"]["username"]
    assert me.json()["user"]["role_codes"] == ["user"]  # provisioned with default role

    # OIDC-only account: no local password.
    user = (await db.execute(User.__table__.select().where(User.username == username))).one()
    assert user.password_hash == ""
    # The standard phone_number claim is captured during provisioning.
    assert me.json()["user"]["phone"] == "+1-555-0100"
    assert user.phone == "+1-555-0100"


async def test_explicit_callback_int_subject(monkeypatch, idp, client, db):
    """GitHub-style callback: the numeric id claim becomes the stringified
    subject, a null email coerces to "", and discovery is never used."""
    from sqlalchemy import select

    from app.models.entities import OauthIdentity, User

    _no_discovery(monkeypatch, idp)
    await seed_admin(db)
    location = await _run_callback(client, "mockhub")
    assert location.startswith(f"{FRONTEND}/auth/callback#")
    assert _frag_params(location)["token"]

    ident = (await db.execute(select(OauthIdentity))).scalars().one()
    assert ident.provider == "mockhub"
    assert ident.subject == "12345"  # int id stringified via subject_claim
    assert ident.email == ""  # nullable email coerced; snapshot column NOT NULL

    user = (await db.execute(select(User).where(User.id == ident.user_id))).scalars().one()
    assert user.password_hash == ""  # OIDC-only account
    assert user.email is None


async def test_second_login_links_same_user(idp, client, db):
    from sqlalchemy import func, select

    from app.models.entities import User

    await seed_admin(db)
    await _run_callback(client)
    await _run_callback(client)
    count = await db.scalar(select(func.count()).select_from(User).where(User.username != "admin"))
    assert count == 1  # same IdP identity -> same local user, no duplicates


async def test_auto_provision_disabled_rejects(monkeypatch, idp, client, db):
    import app.api.auth as auth_api

    await seed_admin(db)
    monkeypatch.setattr(
        auth_api, "build_provider_registry", lambda: _provider(auto_provision=False)
    )
    location = await _run_callback(client)
    assert _frag_params(location).get("error") == "not_allowed"


async def test_state_tamper_rejected(idp, client, db):
    await seed_admin(db)
    login = await client.get("/api/v1/auth/oauth/default/login")
    cookie = login.headers["set-cookie"].split(";")[0]
    callback = await client.get(
        "/api/v1/auth/oauth/default/callback",
        params={"code": "xyz", "state": "forged-state"},
        headers={"Cookie": cookie},
    )
    assert callback.status_code == 302
    assert _frag_params(callback.headers["location"]).get("error") == "state_mismatch"


async def test_missing_cookie_rejected(idp, client):
    callback = await client.get(
        "/api/v1/auth/oauth/default/callback",
        params={"code": "xyz", "state": "anything"},
    )
    assert _frag_params(callback.headers["location"]).get("error") == "state_mismatch"


async def test_login_idp_error_redirects(monkeypatch, idp, client):
    """Unreachable IdP at login: 302 to the SPA error page, never a bare 500."""

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    monkeypatch.setattr(
        idp,
        "_open_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(broken)),
    )
    resp = await client.get("/api/v1/auth/oauth/default/login")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(f"{FRONTEND}/auth/callback#")
    assert _frag_params(resp.headers["location"]).get("error") == "idp_error"


async def test_callback_idp_error_audited(monkeypatch, idp, client, db):
    """Token-endpoint 500 -> #error=idp_error plus an audit row, not a 500."""
    from sqlalchemy import select

    from app.models.entities import AuditLog

    monkeypatch.setattr(
        idp,
        "_open_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(_idp_handler(token_response=httpx.Response(500)))
        ),
    )
    await seed_admin(db)
    location = await _run_callback(client, "mockhub")
    assert _frag_params(location).get("error") == "idp_error"

    row = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.event == "auth.oauth.callback", AuditLog.ok.is_(False)
                )
            )
        )
        .scalars()
        .one()
    )
    assert row.error == "idp_error"


async def test_callback_malformed_token_json(monkeypatch, idp, client, db):
    """A non-JSON token reply (JSONDecodeError is a ValueError) -> idp_error."""
    monkeypatch.setattr(
        idp,
        "_open_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                _idp_handler(
                    token_response=httpx.Response(
                        200,
                        text="<html>not json</html>",
                        headers={"Content-Type": "application/json"},
                    )
                )
            )
        ),
    )
    await seed_admin(db)
    location = await _run_callback(client, "mockhub")
    assert _frag_params(location).get("error") == "idp_error"


async def test_callback_missing_subject_claim(monkeypatch, idp, client, db):
    """userinfo without the configured subject claim -> #error=no_subject."""
    monkeypatch.setattr(
        idp,
        "_open_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(_idp_handler(hub_user={"login": "nosub"}))
        ),
    )
    await seed_admin(db)
    location = await _run_callback(client, "mockhub")
    assert _frag_params(location).get("error") == "no_subject"
