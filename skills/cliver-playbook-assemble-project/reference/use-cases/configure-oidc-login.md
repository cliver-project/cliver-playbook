# Configure OIDC / social login

## Use when

The login page needs external identity providers: Google, GitHub, another
standard OIDC/OAuth2 IdP, or the built-in WeChat / Alipay adapters. The
playbook owns the flow; the project supplies provider configuration and brand
metadata. No project code is required for a built-in provider.

Profile: `web`, `rag`, or `mcp`.

## Do

### 1. Configure providers in `app.yaml`

```yaml
oidc:
  # The backend's public origin as the IdP sees it. Leave empty only when the
  # request's own host/protocol is correct behind the proxy.
  redirect_base: https://app.example.com
  providers:
    google:
      enabled: true
      label: Google
      labels: { zh: 谷歌 }          # lowercase locale tags; keys are normalized
      icon: /icons/google.svg       # square image path or absolute URL
      brand_color: "#4285F4"        # accent and initial-badge fallback
      issuer: https://accounts.google.com
      client_id: "..."
      client_secret: ""             # set from the environment, never here
      scopes: openid profile email
    github:
      enabled: true
      label: GitHub
      brand_color: "#181717"
      authorize_url: https://github.com/login/oauth/authorize
      token_url: https://github.com/login/oauth/access_token
      userinfo_url: https://api.github.com/user
      subject_claim: id             # GitHub returns a numeric account id
      scopes: read:user user:email
    wechat:
      enabled: true
      label: WeChat
      labels: { zh: 微信 }
      brand_color: "#07C160"
      adapter: wechat                # no issuer or endpoint URLs
      client_id: "..."
      client_secret: ""             # the app secret; env only
    alipay:
      enabled: true
      label: Alipay
      brand_color: "#1677FF"
      adapter: alipay
      client_id: "..."
      client_secret: ""             # the application PRIVATE KEY; env only
```

Register the exact callback with the provider:
`<redirect_base>/api/v1/auth/oauth/<provider-key>/callback`.

### 2. Put secrets in the environment

```sh
CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET=...
CLIVER_OIDC__PROVIDERS__WECHAT__CLIENT_SECRET=...
CLIVER_OIDC__PROVIDERS__ALIPAY__CLIENT_SECRET=...
```

The `__` delimiter maps to nested settings. Provider keys are matched
case-insensitively, so YAML `Google:` and the env path `GOOGLE` merge. `.env`
is gitignored; `app.yaml` is checked in.

### 3. Select the token authentication method when the IdP requires it

```yaml
    keycloak:
      enabled: true
      issuer: https://sso.example.com/realms/main
      # client_secret_post (default) | client_secret_basic | none
      token_endpoint_auth_method: client_secret_basic
      token_extra_params: { audience: cliver-app }     # protocol fields rejected
```

- `client_secret_post` — credentials in the token form body (default).
- `client_secret_basic` — HTTP Basic header.
- `none` — public client; only `client_id` is sent, and the secret may be
  empty.

Enabled providers must use `https` endpoints. A local IdP on a loopback or
private network can opt out explicitly with
`oidc.allow_insecure_endpoints: true`; never enable that in production.

The short-lived OAuth state cookie sets `Secure` from the scheme of
`redirect_base` (or `web_base_url`). Pin `oidc.cookie_secure` when TLS
terminates in front of a backend whose configured URLs do not reveal the
public scheme.

### 4. Install the Alipay dependency

```sh
uv add "cliver-playbook-app-user[alipay]==X.Y.Z"
```

The Alipay adapter needs `cryptography` for RSA2 signing. Its `client_secret`
is the application private key; it signs locally and is never transmitted.

### 5. Route outbound IdP traffic through the deployment's egress

The default creates a short-lived client per flow with
`oidc.http_timeout_seconds`. To use a proxy, a private CA, retries, or a shared
connection pool, install a factory before the first login:

```python
from contextlib import asynccontextmanager

import httpx

from cliver_playbook.app.user.auth.oidc import set_http_client_factory

shared = httpx.AsyncClient(proxy="http://egress.internal:3128", verify="/etc/ssl/private-ca.pem")


@asynccontextmanager
async def shared_client():
    yield shared  # close it at application shutdown


set_http_client_factory(shared_client)
```

`set_http_client_factory(None)` restores the default. Tests use the same public
factory with `httpx.MockTransport`.

## Verify

```sh
curl -fsS http://127.0.0.1:8000/api/v1/auth/oauth/providers
```

The response contains only enabled providers, each with
`{key, label, labels, icon, brand_color}`. Open the login page and complete one
round trip per provider. The frontend resolves the active language
(full tag → base tag → `label`), renders `icon`, or a colored initial badge
when only `brand_color` is set.

Then test the denial paths: a disabled provider returns 404, and an enabled
provider with a missing credential or an unknown `adapter` name fails at
startup (`create_app`) rather than at first login.

## Pitfalls

- **Do not put issuer/endpoint URLs on an adapter provider.** The adapter owns
  the authorize URL and the exchange; endpoint fields are ignored.
- **Never log adapter request URLs or exception strings.** The WeChat query
  string carries the app secret and access token; the Alipay private key must
  never leave the process.
- **The Alipay private key is a secret**, not a normal client secret. Load it
  from the environment and keep it out of `.env.example`.
- **`label` is the brand name, not the action.** Keep `WeChat`, not
  `WeChat login`; the button template adds "Continue with …".
- **Callback URI must match byte for byte** with what is registered at the
  IdP, including scheme, host, port, and path.
- **`allow_insecure_endpoints` is development-only.** The token exchange
  carries client credentials.
- **Brand metadata is returned verbatim**; an empty icon and color leave the
  button plain. The user frontend needs no change to render it.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/settings.py`
  — `OidcProviderSettings`, `OidcSettings`.
- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/auth/oidc.py`
  — discovery, token exchange, `set_http_client_factory`.
- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/auth/adapters/`
  — the built-in WeChat/Alipay adapters and the adapter registry.
- `var/playbook/packages/backend/cliver-playbook-app-user/README.md` section
  "Provider adapters".
- Deep dive: `reference/decision-guide.md` row "OIDC login".
