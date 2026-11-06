"""Outbound IdP HTTP client injection: public factory, lifetime, timeout.

The OIDC flow's outbound calls are configurable through one public seam:
``oidc.set_http_client_factory``. Deployments use it for a proxy, a private
CA, transport retries, or a shared connection pool; tests install a
``MockTransport`` through the same API instead of patching a private symbol.

Lifetime contract under test:
- a factory returning an ``httpx.AsyncClient`` hands ownership to this module,
  which closes it after the call;
- a factory returning its own async context manager controls the lifetime, so
  a long-lived shared client stays open;
- a client passed explicitly via ``client=`` always belongs to the caller and
  is never closed.
"""

from contextlib import asynccontextmanager

import httpx
import pytest

from cliver_playbook.app.user.auth import oidc
from cliver_playbook.app.user.auth.oidc import ProviderConfig


def _discovery_handler(issuer: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/openid-configuration"
        return httpx.Response(
            200,
            json={
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "userinfo_endpoint": f"{issuer}/userinfo",
            },
        )

    return handler


async def test_installed_factory_supplies_the_client():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _discovery_handler("https://factory.example.com")(request)

    oidc.set_http_client_factory(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    document = await oidc.discover("https://factory.example.com")

    assert document["issuer"] == "https://factory.example.com"
    assert len(requests) == 1


async def test_factory_created_client_is_closed_after_the_call():
    created = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_discovery_handler("https://closed.example.com"))
        )
        created.append(client)
        return client

    oidc.set_http_client_factory(factory)
    await oidc.discover("https://closed.example.com")

    assert len(created) == 1
    assert created[0].is_closed


async def test_factory_context_manager_can_share_a_client():
    shared = httpx.AsyncClient(
        transport=httpx.MockTransport(_discovery_handler("https://shared.example.com"))
    )

    @asynccontextmanager
    async def factory():
        # A shared client's owner closes it at application shutdown, not per
        # request; the factory's context manager deliberately does not.
        yield shared

    oidc.set_http_client_factory(factory)
    try:
        await oidc.discover("https://shared.example.com")
        assert not shared.is_closed
    finally:
        await shared.aclose()


async def test_explicit_client_is_never_closed():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_discovery_handler("https://explicit.example.com"))
    ) as client:
        await oidc.discover("https://explicit.example.com", client=client)
        assert not client.is_closed


async def test_one_factory_client_serves_a_whole_login_flow():
    factory_calls = []
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "at_test", "token_type": "Bearer"})
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": "idp-user-1"})
        return httpx.Response(404)

    def factory() -> httpx.AsyncClient:
        factory_calls.append(1)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    oidc.set_http_client_factory(factory)
    provider = ProviderConfig(
        key="acme",
        issuer="",
        client_id="client-id",
        client_secret="secret",
        scopes="",
        authorize_url="https://idp.example.com/authorize",
        token_url="https://idp.example.com/token",
        userinfo_url="https://idp.example.com/userinfo",
    )

    identity = await oidc.complete_login(
        provider,
        code="code-1",
        code_verifier="verifier-1",
        redirect_uri="https://app.example.com/auth/callback",
    )

    assert identity.subject == "idp-user-1"
    # One factory client for the flow: token and userinfo share its pool.
    assert factory_calls == [1]
    assert paths == ["/token", "/userinfo"]


async def test_default_factory_uses_the_settings_timeout(monkeypatch):
    monkeypatch.setattr(oidc.get_settings().oidc, "http_timeout_seconds", 2.5)

    async with oidc.get_http_client_factory()() as client:
        assert client.timeout == httpx.Timeout(2.5)


async def test_setting_none_restores_the_default_factory():
    calls = []

    def custom() -> httpx.AsyncClient:
        calls.append(1)
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_discovery_handler("https://custom.example.com"))
        )

    oidc.set_http_client_factory(custom)
    oidc.set_http_client_factory(None)

    async with oidc.get_http_client_factory()() as client:
        assert isinstance(client, httpx.AsyncClient)
    assert calls == []


def test_factory_must_be_callable():
    with pytest.raises(TypeError, match="callable"):
        oidc.set_http_client_factory(object())  # type: ignore[arg-type]
