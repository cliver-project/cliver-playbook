# cliver-playbook-app-user

Identity package of the cliver-playbook library — accounts, roles and
permissions, session and static tokens, OIDC login against external identity
providers, and an OAuth 2.1 provider surface for AI-agent clients.

Builds on [`cliver-playbook-app-basic`](../cliver-playbook-app-basic): it
subclasses that package's `Settings`, uses its runtime (`runtime.engine()`,
`runtime.session_factory()`, `db.session.get_db`) and its declarative base,
and contributes its own `ROUTERS`, migration chain and self-application.

## What is inside

| Area | Path (under `src/cliver_playbook/app/user/`) | Notes |
|---|---|---|
| Settings | `settings.py` | `Settings(basic.Settings)`: secret key, login policy, OIDC registry, OAuth 2.1 knobs. |
| Routers | `api/routes.py` | `ROUTERS: list[APIRouter]` — `/api/v1/auth` + `/api/v1/admin`, including the section-agnostic settings surface (ADR-0015/0021). |
| Identity | `auth/` | Passwords, tokens, permissions catalog with the `*` superuser wildcard, RBAC dependencies, OIDC client, provider adapters, OAuth 2.1 provider, audit writer. |
| Runtime settings | `settings_section.py`, `api/admin_settings.py` | This package's identity-policy section plus the generic describe/update/reset HTTP layer delegated to each owning package (ADR-0021). |
| Domain | `api/`, `services/`, `schemas/`, `models/entities.py` | Endpoints + service layer; tables: users, roles, user_roles, role_permissions, oauth_identities, oauth_clients, oauth_codes, oauth_refresh_tokens, auth_tokens, audit_logs. |
| Migrations | `alembic/` | Own chain, version table `alembic_version_user`; seeds the admin/user roles and the initial admin account, and pins the admin role to `*`. |
| Application | `app.py`, `__main__.py` | `create_app()` composes basic + user; `python -m cliver_playbook.app.user`. |

The OAuth 2.1 provider (`auth/oauth21.py`) adds root-level routes
(`/.well-known/*`, token, registration, revocation) that are not part of
`ROUTERS`: they come from the MCP SDK at call time, so `create_app` adds them
through `mount_oauth_routes(app)`.

## Provider adapters

Standard OIDC/OAuth2 providers are pure configuration: discovery
(`issuer`) or explicit endpoints (`authorize_url` / `token_url` /
`userinfo_url`). Providers whose wire protocol is not OAuth2 select a
registered adapter with `oidc.providers.<key>.adapter` (ADR-0024). `wechat`
(Open Platform QR-connect) and `alipay` (RSA2-signed gateway) are built in;
a project can register its own with
`cliver_playbook.app.user.auth.adapters.register_adapter` before `create_app`.
`create_app` validates every enabled provider's adapter name and fails startup
with the provider key and registered names when one is misspelled, instead of
returning a 500 on the first login. Adapters own the authorize URL and the
code-for-identity exchange, so no endpoint URLs are needed and upstream tokens
never pass through a playbook HTTP endpoint.

The Alipay adapter needs the optional RSA dependency:

```bash
python -m pip install -e ".[alipay]"   # cryptography
```

An adapter may expose `validate_config(config)`; `create_app` calls it after
building the registry, so bad adapter-specific configuration fails startup.
Alipay uses `adapter_options.authorize_url` and `adapter_options.gateway_url`
to target its sandbox (or a compatible proxy). Both must be absolute `https`
URLs; unset values use the production Alipay hosts. Unknown option names are
rejected at startup.

```yaml
alipay:
  enabled: true
  adapter: alipay
  adapter_options:
    authorize_url: https://openauth-sandbox.dl.alipaydev.com/oauth2/publicAppAuthorize.htm
    gateway_url: https://openapi-sandbox.dl.alipaydev.com/gateway.do
```

Standard providers choose how the token exchange authenticates the client:
`oidc.providers.<key>.token_endpoint_auth_method` is `client_secret_post`
(the default, credentials in the form body), `client_secret_basic` (an HTTP
Basic header), or `none` (a public client: only `client_id` is sent, and
`client_secret` may be empty). `token_extra_params` adds provider-specific
form fields; protocol fields such as `code` and `client_secret` are rejected.
Enabled providers must use `https` issuer and endpoint URLs.
`oidc.allow_insecure_endpoints: true` is the explicit local-development
escape hatch for a plain-http IdP on a loopback or private network; never
enable it in production.

Provider buttons can carry brand metadata: `label` is the default text,
`labels` maps lowercase locale tags to overrides (e.g. `{en: WeChat, zh: 微信}`),
`icon` is a square image path or URL, and `brand_color` is a CSS color.
`/api/v1/auth/oauth/providers` returns all four verbatim as
`{key, label, labels, icon, brand_color}`; the SPA resolves the active
language and renders the configured icon, or a colored initial badge when only
`brand_color` is set. Keep `label` to the brand name (e.g. `WeChat`, not
`WeChat login`) when the localized "Continue with …" button template is used.

Outbound IdP traffic (discovery, token, userinfo) goes through one
process-wide client factory,
`cliver_playbook.app.user.auth.oidc.set_http_client_factory`. The default
creates a short-lived `httpx.AsyncClient` per flow with
`oidc.http_timeout_seconds` (10 s). Install a factory to send IdP calls
through a proxy or a private CA, add transport retries, or reuse a shared
connection pool; `set_http_client_factory(None)` restores the default. The
factory returns an async context manager yielding an `httpx.AsyncClient`:
return the client directly to have it closed after the call, or wrap a
long-lived client in `contextlib.asynccontextmanager` to keep it open.

```python
from contextlib import asynccontextmanager

import httpx

from cliver_playbook.app.user.auth.oidc import set_http_client_factory

shared = httpx.AsyncClient(
    proxy="http://egress.internal:3128",
    verify="/etc/ssl/private-ca.pem",
)


@asynccontextmanager
async def shared_client():
    yield shared  # close it yourself at application shutdown


set_http_client_factory(shared_client)
```

The low-level helpers also accept an explicit `client=`; that client belongs
to the caller and is never closed by this package. Tests install an
`httpx.MockTransport` through the same public factory.

## Install

```bash
python -m pip install -e ../cliver-playbook-app-basic   # dependency first
python -m pip install -e .                              # or: pip install -e ../basic -e .
```

Editable installs of sibling packages coexist in one virtualenv: the
`cliver_playbook` and `cliver_playbook.app` namespace directories are
PEP 420 — deliberately no `__init__.py` — so every package's portion merges.

## Run standalone

```bash
docker compose up -d db        # or point CLIVER_DATABASE_URL at PostgreSQL
python -m cliver_playbook.app.user --reload
```

First run: apply both migration chains (basic, then user) — the seed prints
the initial admin password once.

## Migrate

```bash
python -c "
from cliver_playbook.app.basic.alembic import run_migrations_online
from cliver_playbook.app.user.alembic import run_migrations_online as run_user
run_migrations_online(); run_user()
"
# interactive, from this directory:
alembic upgrade head
```

## Test

```bash
python -m pytest        # needs PostgreSQL; creates and drops a temp database
```

The suite binds the composed application (`create_app`) and applies both
migration chains, so it exercises the same path a project's initialization
takes. `tests/fixtures/app.yaml` supplies the configuration layer (pinned via
`CLIVER_CONFIG_FILE`), keeping the suite independent of the surrounding
checkout's `app.yaml`.
