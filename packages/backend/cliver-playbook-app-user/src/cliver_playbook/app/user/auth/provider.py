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

# Token-request form fields the flow itself controls. `token_extra_params`
# may not set them: an override could silently replace the code or the client
# authentication fields.
TOKEN_REQUEST_RESERVED = frozenset(
    {
        "grant_type",
        "code",
        "redirect_uri",
        "code_verifier",
        "client_id",
        "client_secret",
    }
)


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
    are unused. `adapter_options` carries adapter-specific settings, such as
    the built-in Alipay adapter's ``authorize_url`` and ``gateway_url``
    overrides.

    `subject_claim` names the userinfo field carrying the provider-side
    stable user id: "sub" for standard OIDC, "id" for GitHub-style APIs
    returning a numeric account id. Adapters choose their own subject, so this
    field is ignored when `adapter` is set.

    `token_endpoint_auth_method` decides where the standard token request
    carries the client credentials: the form body (``client_secret_post``,
    the default), an HTTP Basic header (``client_secret_basic``), or neither
    (``none``, a public client). `token_extra_params` adds provider-specific
    form fields. Both are ignored when `adapter` is set.

    `label` is the UI button text; empty means the edge falls back to
    `key.title()`. `labels` supplies per-locale overrides keyed by a lowercase
    locale tag. `icon` is an optional brand image URL/path and `brand_color`
    a CSS color for the accent or the fallback initial badge; the providers
    endpoint returns all three verbatim for the SPA to render.
    """

    key: str  # URL segment + oauth_identities.provider value
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    auto_provision: bool = True
    default_role: str = "user"
    label: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)
    icon: str = ""
    brand_color: str = ""
    subject_claim: str = "sub"
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    adapter: str = ""
    # Adapter-specific settings, interpreted only by the selected adapter.
    adapter_options: Mapping[str, str] = field(default_factory=dict)
    # How the token request authenticates the client (RFC 6749 section 2.3):
    # "client_secret_post", "client_secret_basic", or "none".
    token_endpoint_auth_method: str = "client_secret_post"
    # Provider-specific form fields added to the token request.
    token_extra_params: Mapping[str, str] = field(default_factory=dict)


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

    An adapter may also define ``validate_config(config)``. ``create_app``
    calls it while building the startup registry, so adapter-specific options
    fail fast; adapters without it skip this optional check.
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
