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
| Routers | `api/routes.py` | `ROUTERS: list[APIRouter]` — `/api/v1/auth` + `/api/v1/admin` (ADR-0015). |
| Identity | `auth/` | Passwords, tokens, permissions catalog, RBAC dependencies, OIDC client, OAuth 2.1 provider, audit writer. |
| Domain | `api/`, `services/`, `schemas/`, `models/entities.py` | Endpoints + service layer; tables: users, roles, user_roles, role_permissions, oauth_identities, oauth_clients, oauth_codes, oauth_refresh_tokens, auth_tokens, audit_logs. |
| Migrations | `alembic/` | Own chain, version table `alembic_version_user`; seeds the admin/user roles and the initial admin account. |
| Application | `app.py`, `__main__.py` | `create_app()` composes basic + user; `python -m cliver_playbook.app.user`. |

The OAuth 2.1 provider (`auth/oauth21.py`) adds root-level routes
(`/.well-known/*`, token, registration, revocation) that are not part of
`ROUTERS`: they come from the MCP SDK at call time, so `create_app` adds them
through `mount_oauth_routes(app)`.

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
