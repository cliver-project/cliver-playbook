"""WeChat Open Platform QR-connect adapter.

WeChat is not OAuth2-shaped: the authorize page is ``qrconnect``, the token
exchange and profile lookup are plain GETs, and failures arrive as HTTP 200
with an ``errcode`` field inside the body.

Security note: the app secret travels in the token request query string
(WeChat's protocol requirement, over HTTPS). The module pins httpx's logger
below INFO so those URLs never reach application logs, and every error raised
here names only the step and WeChat's numeric error code — never the request
URL, which carries the secret and the upstream access token.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from cliver_playbook.app.user.auth.provider import (
    Identity,
    ProviderAdapterError,
    ProviderConfig,
)

# WeChat carries the app secret and the upstream access token in query strings,
# while httpx logs every request URL at INFO. Pin the library logger below INFO
# for the process so those URLs can never reach application logs. The identity
# package owns this setting: every HTTP call it makes is to an IdP, where URLs
# and headers are credential-bearing.
logging.getLogger("httpx").setLevel(logging.WARNING)

AUTHORIZE_ENDPOINT = "https://open.weixin.qq.com/connect/qrconnect"
TOKEN_ENDPOINT = "https://api.weixin.qq.com/sns/oauth2/access_token"
USERINFO_ENDPOINT = "https://api.weixin.qq.com/sns/userinfo"


def _payload(response: httpx.Response, step: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderAdapterError(f"wechat {step} response is not JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderAdapterError(f"wechat {step} response is not an object")
    if payload.get("errcode"):
        raise ProviderAdapterError(f"wechat {step} error {payload['errcode']}")
    return payload


class WeChatAdapter:
    """The built-in ``wechat`` adapter (Open Platform QR-connect)."""

    def authorize_url(
        self,
        config: ProviderConfig,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str = "",
        code_challenge_method: str = "S256",
    ) -> str:
        # QR-connect ignores PKCE; the one-time code + app secret is the
        # protocol's own exchange. Scope is fixed by the endpoint.
        query = urlencode(
            {
                "appid": config.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": state,
            }
        )
        return f"{AUTHORIZE_ENDPOINT}?{query}#wechat_redirect"

    async def complete(
        self,
        config: ProviderConfig,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client: httpx.AsyncClient,
    ) -> Identity:
        token_response = await client.get(
            TOKEN_ENDPOINT,
            params={
                "appid": config.client_id,
                "secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        token_payload = _payload(token_response, "token")

        openid = token_payload.get("openid")
        access_token = token_payload.get("access_token")
        if not isinstance(openid, str) or not openid:
            raise ProviderAdapterError("wechat token response is missing openid")
        if not isinstance(access_token, str) or not access_token:
            raise ProviderAdapterError("wechat token response is missing access_token")

        userinfo_response = await client.get(
            USERINFO_ENDPOINT,
            params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
        )
        userinfo_response.raise_for_status()
        profile = _payload(userinfo_response, "userinfo")

        response_openid = profile.get("openid")
        if isinstance(response_openid, str) and response_openid and response_openid != openid:
            # Fail closed: the profile must belong to the account the token
            # was issued for.
            raise ProviderAdapterError("wechat userinfo subject mismatch")

        claims = dict(profile)
        nickname = profile.get("nickname")
        if isinstance(nickname, str) and nickname:
            claims["name"] = nickname
        picture = profile.get("headimgurl")
        if isinstance(picture, str) and picture:
            claims["picture"] = picture
        return Identity(subject=openid, claims=claims)
