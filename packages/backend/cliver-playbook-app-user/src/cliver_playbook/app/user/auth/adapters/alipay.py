"""Alipay RSA2-signed gateway adapter.

Alipay is not OAuth2-shaped: the browser goes to a public authorize page, and
both the token exchange and the profile lookup are form POSTs to one gateway,
each carrying an RSA-SHA256 (RSA2) signature. The application private key is
configured as the provider's ``client_secret``; it is used locally to sign
requests and never transmitted. ``cryptography`` is an optional dependency
(``cliver-playbook-app-user[alipay]``) imported only when the adapter runs.

P0 trusts TLS for the gateway responses and does not verify Alipay's response
signature; see the provider-adapter ADR for the follow-up.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from cliver_playbook.app.user.auth.provider import (
    Identity,
    ProviderAdapterError,
    ProviderConfig,
)

AUTHORIZE_ENDPOINT = "https://openauth.alipay.com/oauth2/publicAppAuthorize.htm"
GATEWAY_ENDPOINT = "https://openapi.alipay.com/gateway.do"
_SCOPE = "auth_user"
# China Standard Time has no DST; a fixed offset avoids a tzdata dependency.
_CST = timezone(timedelta(hours=8))


def sign_content(params: Mapping[str, str]) -> str:
    """The pre-sign string: ASCII-sorted ``k=v`` pairs joined by ``&``.

    Values are raw (not URL-encoded); empty values and the top-level ``sign``
    field are excluded. ``sign_type`` stays in — Alipay's verifier recomputes
    exactly this string.
    """
    return "&".join(
        f"{key}={value}" for key, value in sorted(params.items()) if key != "sign" and value
    )


def _load_private_key(raw: str):
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ProviderAdapterError(
            "alipay adapter requires the `cryptography` package; install "
            "cliver-playbook-app-user[alipay]"
        ) from exc

    pem = raw.replace("\\n", "\n").strip()
    # Alipay's key tool exports either a PEM block or bare Base64 DER; accept
    # both by wrapping the latter in a PKCS#8 header.
    if "BEGIN" not in pem:
        body = "".join(pem.split())
        lines = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
        pem = f"-----BEGIN PRIVATE KEY-----\n{lines}\n-----END PRIVATE KEY-----\n"
    try:
        return serialization.load_pem_private_key(pem.encode(), password=None)
    except ValueError as exc:
        # Never echo the key material in the message.
        raise ProviderAdapterError("alipay private key is not a valid PEM key") from exc


def sign(params: Mapping[str, str], private_key: str) -> str:
    """RSA2-sign the pre-sign string; returns standard Base64."""
    # Load first: _load_private_key turns a missing `cryptography` into the
    # extra-installation message instead of a bare ImportError.
    key = _load_private_key(private_key)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signature = key.sign(
        sign_content(params).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _timestamp() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _error_message(step: str, body: Mapping[str, Any]) -> str:
    details = " ".join(str(part) for part in (body.get("code"), body.get("sub_code")) if part)
    return f"alipay {step} error {details}".strip()


class AlipayAdapter:
    """The built-in ``alipay`` adapter (RSA2-signed OpenAPI gateway)."""

    def authorize_url(
        self,
        config: ProviderConfig,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str = "",
        code_challenge_method: str = "S256",
    ) -> str:
        # The authorize page is a plain browser redirect; signing starts at
        # the gateway calls. PKCE is not part of this protocol.
        query = urlencode(
            {
                "app_id": config.client_id,
                "scope": _SCOPE,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{AUTHORIZE_ENDPOINT}?{query}"

    async def complete(
        self,
        config: ProviderConfig,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client: httpx.AsyncClient,
    ) -> Identity:
        token_body = await self._post(
            config,
            "alipay.system.oauth.token",
            {"grant_type": "authorization_code", "code": code},
            client=client,
            step="token",
        )
        access_token = token_body.get("access_token")
        user_id = token_body.get("user_id")
        if not isinstance(access_token, str) or not access_token:
            raise ProviderAdapterError("alipay token response is missing access_token")
        if not isinstance(user_id, str) or not user_id:
            raise ProviderAdapterError("alipay token response is missing user_id")

        profile = await self._post(
            config,
            "alipay.user.info.share",
            {"auth_token": access_token},
            client=client,
            step="userinfo",
        )
        response_user_id = profile.get("user_id")
        if isinstance(response_user_id, str) and response_user_id and response_user_id != user_id:
            raise ProviderAdapterError("alipay userinfo subject mismatch")

        claims = dict(profile)
        nickname = profile.get("nick_name")
        if isinstance(nickname, str) and nickname:
            claims["name"] = nickname
        avatar = profile.get("avatar")
        if isinstance(avatar, str) and avatar:
            claims["picture"] = avatar
        return Identity(subject=user_id, claims=claims)

    async def _post(
        self,
        config: ProviderConfig,
        method: str,
        extra: dict[str, str],
        *,
        client: httpx.AsyncClient,
        step: str,
    ) -> dict[str, Any]:
        params = {
            "app_id": config.client_id,
            "method": method,
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": _timestamp(),
            "version": "1.0",
            **extra,
        }
        params["sign"] = sign(params, config.client_secret)
        response = await client.post(GATEWAY_ENDPOINT, data=params)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderAdapterError(f"alipay {step} response is not JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderAdapterError(f"alipay {step} response is not an object")

        error = payload.get("error_response")
        if isinstance(error, dict):
            raise ProviderAdapterError(_error_message(step, error))
        body = payload.get(f"{method.replace('.', '_')}_response")
        if not isinstance(body, dict):
            raise ProviderAdapterError(f"alipay {step} response is missing its body")
        if body.get("code") != "10000":
            raise ProviderAdapterError(_error_message(step, body))
        return body
