"""OIDC client login: provider listing, authorize redirect, full callback
flow, identity re-linking, auto-provision, and state tampering.

The IdP never exists — every outbound call (discovery, token, userinfo) is
served by an httpx.MockTransport installed through the `_open_client` seam,
so the whole flow runs with zero network.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.auth.oidc import ProviderConfig
from tests.helpers import seed_admin

ISSUER = "https://idp.example.com"
FRONTEND = "http://127.0.0.1:5173"


def _idp_handler(sub: str = "idp-user-1", email: str = "dev@example.com"):
    """A minimal standards-shaped IdP: discovery + token + userinfo."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
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
            return httpx.Response(200, json={"access_token": "at_test", "token_type": "Bearer"})
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

    return handler


def _provider(auto_provision: bool = True) -> dict[str, ProviderConfig]:
    return {
        "default": ProviderConfig(
            key="default",
            issuer=ISSUER,
            client_id="client-1",
            client_secret="secret-1",
            scopes="openid profile email",
            auto_provision=auto_provision,
            default_role="user",
        )
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


async def test_providers_endpoint_lists_configured(idp, client):
    resp = await client.get("/api/v1/auth/oauth/providers")
    assert resp.status_code == 200
    assert resp.json() == {"providers": [{"key": "default", "label": "SSO"}]}


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


async def _run_callback(client) -> str:
    """Drive login -> callback with the IdP 'issuing' code xyz; returns the
    final redirect Location."""
    login = await client.get("/api/v1/auth/oauth/default/login")
    state = {k: v[0] for k, v in parse_qs(urlparse(login.headers["location"]).query).items()}[
        "state"
    ]
    cookie = login.headers["set-cookie"].split(";")[0]
    callback = await client.get(
        "/api/v1/auth/oauth/default/callback",
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
