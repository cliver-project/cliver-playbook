"""Provider adapter extension point: registry, identity contract, built-ins."""

import base64
import logging
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest

from cliver_playbook.app.user.auth.adapters import (
    Identity,
    ProviderAdapterError,
    adapter_names,
    get_adapter,
    register_adapter,
)
from cliver_playbook.app.user.auth.adapters.alipay import AlipayAdapter, sign_content
from cliver_playbook.app.user.auth.adapters.wechat import WeChatAdapter
from cliver_playbook.app.user.auth.provider import ProviderConfig


class _FakeAdapter:
    """Minimal adapter used to prove project registration works."""

    def authorize_url(
        self,
        config,
        *,
        state,
        redirect_uri,
        code_challenge="",
        code_challenge_method="S256",
    ):
        return "https://fake.example/authorize"

    async def complete(self, config, *, code, code_verifier, redirect_uri, client):
        return Identity(subject="fake-subject")


def test_builtin_adapters_are_registered():
    assert {"wechat", "alipay"} <= adapter_names()


def test_register_and_get_custom_adapter():
    adapter = _FakeAdapter()
    register_adapter("test-custom", adapter)
    assert get_adapter("test-custom") is adapter
    assert "test-custom" in adapter_names()


def test_duplicate_adapter_registration_rejected():
    adapter = _FakeAdapter()
    register_adapter("test-duplicate", adapter)
    with pytest.raises(ValueError, match="already registered"):
        register_adapter("test-duplicate", adapter)


def test_unknown_adapter_raises_key_error():
    with pytest.raises(KeyError, match="unknown provider adapter"):
        get_adapter("test-missing")


def test_identity_reads_normalized_claims():
    identity = Identity(
        subject="u-1",
        claims={
            "name": "Ada",
            "email": "ada@example.com",
            "phone_number": "+1-555-0100",
            "picture": "https://example.com/ada.png",
        },
    )
    assert identity.subject == "u-1"
    assert identity.name == "Ada"
    assert identity.email == "ada@example.com"
    assert identity.phone_number == "+1-555-0100"
    assert identity.picture == "https://example.com/ada.png"


def test_identity_falls_back_to_preferred_username_and_subject():
    identity = Identity(subject="u-2", claims={"preferred_username": "ada"})
    assert identity.name == "ada"
    assert identity.display_name == "ada"
    empty = Identity(subject="u-3")
    assert empty.email == ""
    assert empty.display_name == "u-3"


# ---------------------------------------------------------------------------
# Built-in adapters
# ---------------------------------------------------------------------------


def _config(adapter: str, *, secret: str = "secret") -> ProviderConfig:
    return ProviderConfig(
        key=adapter,
        issuer="",
        client_id=f"{adapter}-client",
        client_secret=secret,
        scopes="",
        adapter=adapter,
    )


def test_wechat_authorize_url_carries_qrconnect_query():
    url = WeChatAdapter().authorize_url(
        _config("wechat"),
        state="st-1",
        redirect_uri="https://app.example/api/v1/auth/oauth/wechat/callback",
    )
    assert url.startswith("https://open.weixin.qq.com/connect/qrconnect?")
    assert url.endswith("#wechat_redirect")
    assert parse_qs(urlparse(url).query) == {
        "appid": ["wechat-client"],
        "redirect_uri": ["https://app.example/api/v1/auth/oauth/wechat/callback"],
        "response_type": ["code"],
        "scope": ["snsapi_login"],
        "state": ["st-1"],
    }


async def test_wechat_complete_exchanges_code_and_normalizes_identity():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/sns/oauth2/access_token":
            assert request.url.params["appid"] == "wechat-client"
            assert request.url.params["secret"] == "secret"
            assert request.url.params["code"] == "the-code"
            assert request.url.params["grant_type"] == "authorization_code"
            return httpx.Response(200, json={"access_token": "at-1", "openid": "openid-1"})
        if request.url.path == "/sns/userinfo":
            assert request.url.params["access_token"] == "at-1"
            assert request.url.params["openid"] == "openid-1"
            return httpx.Response(
                200,
                json={
                    "openid": "openid-1",
                    "nickname": "Ada",
                    "headimgurl": "https://img.example/ada.png",
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        identity = await WeChatAdapter().complete(
            _config("wechat"),
            code="the-code",
            code_verifier="ignored",
            redirect_uri="https://app.example/callback",
            client=client,
        )
    assert calls == ["/sns/oauth2/access_token", "/sns/userinfo"]
    assert identity.subject == "openid-1"
    assert identity.name == "Ada"
    assert identity.picture == "https://img.example/ada.png"


@pytest.mark.parametrize(
    ("step", "payload"),
    [
        ("token", {"errcode": 40029, "errmsg": "invalid code"}),
        ("userinfo", {"errcode": 40003, "errmsg": "invalid openid"}),
    ],
)
async def test_wechat_errcode_in_200_response_raises(step, payload):
    """WeChat reports failures inside a 200 body; the adapter must not treat
    that as success."""

    def handler(request: httpx.Request) -> httpx.Response:
        if step == "userinfo" and request.url.path == "/sns/oauth2/access_token":
            return httpx.Response(200, json={"access_token": "at-1", "openid": "openid-1"})
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAdapterError, match=f"wechat {step}"):
            await WeChatAdapter().complete(
                _config("wechat"),
                code="bad",
                code_verifier="",
                redirect_uri="https://app.example/callback",
                client=client,
            )


async def test_wechat_rejects_subject_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sns/oauth2/access_token":
            return httpx.Response(200, json={"access_token": "at-1", "openid": "openid-1"})
        return httpx.Response(200, json={"openid": "someone-else", "nickname": "Eve"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAdapterError, match="subject mismatch"):
            await WeChatAdapter().complete(
                _config("wechat"),
                code="the-code",
                code_verifier="",
                redirect_uri="https://app.example/callback",
                client=client,
            )


async def test_wechat_secret_is_not_written_to_logs(caplog):
    """The token URL carries the app secret, while httpx logs request URLs at
    INFO; the adapter must keep that record out of application logs."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sns/oauth2/access_token":
            return httpx.Response(200, json={"access_token": "at-1", "openid": "openid-1"})
        return httpx.Response(200, json={"openid": "openid-1", "nickname": "Ada"})

    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await WeChatAdapter().complete(
                _config("wechat", secret="super-secret-value"),
                code="the-code",
                code_verifier="",
                redirect_uri="https://app.example/callback",
                client=client,
            )
    assert "super-secret-value" not in caplog.text


async def test_wechat_missing_token_fields_raise():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"openid": "o"}))
    ) as client:
        with pytest.raises(ProviderAdapterError, match="access_token"):
            await WeChatAdapter().complete(
                _config("wechat"),
                code="the-code",
                code_verifier="",
                redirect_uri="https://app.example/callback",
                client=client,
            )


def _rsa_keypair():
    """A throwaway RSA keypair for signing tests (skip without the extra)."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _assert_alipay_signature(request: httpx.Request, public_key) -> dict[str, str]:
    """Verify an Alipay gateway request signature; returns the signed params."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    params = dict(parse_qsl(request.content.decode()))
    signature = base64.b64decode(params.pop("sign"))
    public_key.verify(
        signature,
        sign_content(params).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return params


def test_alipay_authorize_url_shape():
    url = AlipayAdapter().authorize_url(
        _config("alipay"),
        state="st-1",
        redirect_uri="https://app.example/api/v1/auth/oauth/alipay/callback",
    )
    assert url.startswith("https://openauth.alipay.com/oauth2/publicAppAuthorize.htm?")
    assert parse_qs(urlparse(url).query) == {
        "app_id": ["alipay-client"],
        "scope": ["auth_user"],
        "redirect_uri": ["https://app.example/api/v1/auth/oauth/alipay/callback"],
        "state": ["st-1"],
    }


def test_alipay_sign_content_sorts_and_skips_empty_values():
    assert (
        sign_content({"b": "2", "a": "1", "empty": "", "sign": "ignored", "sign_type": "RSA2"})
        == "a=1&b=2&sign_type=RSA2"
    )


@pytest.mark.parametrize("escaped", [False, True], ids=["pem", "literal-backslash-n"])
async def test_alipay_complete_signs_gateway_calls_and_normalizes_identity(escaped):
    pem, public_key = _rsa_keypair()
    sent_secret = pem.replace("\n", "\\n") if escaped else pem
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://openapi.alipay.com/gateway.do"
        params = _assert_alipay_signature(request, public_key)
        methods.append(params["method"])
        assert params["app_id"] == "alipay-client"
        assert params["sign_type"] == "RSA2"
        assert params["charset"] == "utf-8"
        assert params["version"] == "1.0"
        assert "timestamp" in params
        if params["method"] == "alipay.system.oauth.token":
            assert params["grant_type"] == "authorization_code"
            assert params["code"] == "the-code"
            return httpx.Response(
                200,
                json={
                    "alipay_system_oauth_token_response": {
                        "code": "10000",
                        "access_token": "at-1",
                        "user_id": "2088",
                    }
                },
            )
        if params["method"] == "alipay.user.info.share":
            assert params["auth_token"] == "at-1"
            return httpx.Response(
                200,
                json={
                    "alipay_user_info_share_response": {
                        "code": "10000",
                        "user_id": "2088",
                        "nick_name": "Ada",
                        "avatar": "https://img.example/ada.png",
                    }
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        identity = await AlipayAdapter().complete(
            _config("alipay", secret=sent_secret),
            code="the-code",
            code_verifier="ignored",
            redirect_uri="https://app.example/callback",
            client=client,
        )
    assert methods == ["alipay.system.oauth.token", "alipay.user.info.share"]
    assert identity.subject == "2088"
    assert identity.name == "Ada"
    assert identity.picture == "https://img.example/ada.png"


@pytest.mark.parametrize(
    "payload",
    [
        {"alipay_system_oauth_token_response": {"code": "40002", "msg": "Invalid Arguments"}},
        {"error_response": {"code": "40002", "msg": "Invalid Arguments"}},
        {"alipay_system_oauth_token_response": {}},
    ],
    ids=["business-error", "gateway-error", "missing-body"],
)
async def test_alipay_gateway_error_raises(payload):
    pem, _ = _rsa_keypair()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ProviderAdapterError, match="alipay token"):
            await AlipayAdapter().complete(
                _config("alipay", secret=pem),
                code="bad",
                code_verifier="",
                redirect_uri="https://app.example/callback",
                client=client,
            )
