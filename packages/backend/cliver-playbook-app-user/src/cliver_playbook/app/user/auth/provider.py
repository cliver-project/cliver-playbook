"""The provider contract: configuration, identity, and the adapter seam.

Standard OIDC/OAuth2 providers are driven by ``auth.oidc`` directly. Providers
whose wire protocol is not OAuth2 (WeChat's QR-connect, Alipay's signed
gateway) plug in through ``ProviderAdapter``: an adapter builds the authorize
URL and performs the whole code-for-identity exchange, so the upstream access
token never leaves the adapter process.

Keeping the contract in this module (rather than in ``auth.oidc``) lets the
built-in adapters import it without a circular dependency on the flow code.
``auth.oidc`` re-exports ``ProviderConfig`` for existing importers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class ProviderConfig:
    """One registered external IdP.

    Two complementary endpoint shapes (the settings model enforces that an
    enabled provider has exactly one of them):
    - `issuer` set: the three endpoints come from OIDC discovery;
    - explicit `authorize_url`/`token_url`/`userinfo_url`: for plain OAuth2
      services without a discovery document (e.g. GitHub).

    `adapter` non-empty selects a registered ``ProviderAdapter`` instead of the
    standard OAuth2 flow; in that case the three endpoint fields and `issuer`
    are unused.

    `subject_claim` names the userinfo field carrying the provider-side
    stable user id: "sub" for standard OIDC, "id" for GitHub-style APIs
    returning a numeric account id. Adapters choose their own subject, so this
    field is ignored when `adapter` is set.

    `label` is the UI button text; empty means the edge falls back to
    `key.title()`.
    """

    key: str  # URL segment + oauth_identities.provider value
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    auto_provision: bool = True
    default_role: str = "user"
    label: str = ""
    subject_claim: str = "sub"
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    adapter: str = ""


@dataclass(frozen=True)
class Identity:
    """A provider-verified identity, normalized for the rest of the app.

    `subject` is the provider-side stable user id stored in
    ``oauth_identities.subject``. `claims` holds the canonical profile fields
    (``name``, ``picture``, ``email``, ``phone_number``) plus any
    provider-specific extras; the properties below coerce missing or non-string
    values to ``""`` so provisioning and linking never see ``None``.
    """

    subject: str
    claims: Mapping[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return _claim(self.claims, "name") or _claim(self.claims, "preferred_username")

    @property
    def email(self) -> str:
        return _claim(self.claims, "email")

    @property
    def phone_number(self) -> str:
        return _claim(self.claims, "phone_number")

    @property
    def picture(self) -> str:
        return _claim(self.claims, "picture")

    @property
    def display_name(self) -> str:
        return self.name or self.email or self.subject[:32]


class ProviderAdapterError(Exception):
    """The upstream provider rejected the request or returned an unusable reply.

    Messages must stay free of request URLs and credentials: WeChat carries its
    app secret in the token request query string. The flow maps this error to
    the ordinary ``idp_error`` outcome, so no provider detail reaches the user.
    """


class ProviderAdapter(Protocol):
    """The seam for providers whose wire protocol is not standard OAuth2.

    Implementations are registered by name (``adapters.register_adapter``) and
    selected through ``OidcProviderSettings.adapter``. Built-ins: ``wechat``
    and ``alipay``. A project may register its own adapter at import time.

    ``authorize_url`` is synchronous: no network call belongs on the browser
    redirect. ``complete`` owns the entire code-for-identity exchange, so
    whatever upstream token it obtains stays local; it must return an
    ``Identity`` or raise ``ProviderAdapterError`` (HTTP/transport failures may
    propagate as ``httpx.HTTPError`` for the flow to classify).
    """

    def authorize_url(
        self,
        config: ProviderConfig,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str = "",
        code_challenge_method: str = "S256",
    ) -> str: ...

    async def complete(
        self,
        config: ProviderConfig,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client: httpx.AsyncClient,
    ) -> Identity: ...


def _claim(claims: Mapping[str, Any], name: str) -> str:
    value = claims.get(name)
    return value if isinstance(value, str) else ("" if value is None else str(value))
