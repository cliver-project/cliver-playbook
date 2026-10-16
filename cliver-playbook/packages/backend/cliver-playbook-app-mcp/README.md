# cliver-playbook-app-mcp

MCP package of the cliver-playbook library — serves the Model Context Protocol
over streamable HTTP and stdio, with an optional bearer gate, agent identity on
every audit row, and the identity package's OAuth 2.1 provider as the way
agents obtain tokens.

Builds on [`cliver-playbook-app-user`](../cliver-playbook-app-user) (and
through it on [`cliver-playbook-app-basic`](../cliver-playbook-app-basic)):
it subclasses the user package's `Settings`, uses the basic package's runtime
and declarative base, reads the identity tables, and contributes its own
`ROUTERS` and self-application. It owns no tables and no migration chain.

## What is inside

| Area | Path (under `src/cliver_playbook/app/mcp/`) | Notes |
|---|---|---|
| Settings | `settings.py` | `Settings(user.Settings)` + the `mcp` block (auth switch, agent-type allowlist, concurrency). |
| Routers | `api/routes.py` | `ROUTERS: list[APIRouter]` — the protocol endpoint at `/mcp` and `/api/v1/mcp` views (ADR-0017). |
| Protocol endpoint | `api/streamable.py` | The SDK's ASGI endpoint as a plain route; the session manager is installed and entered here. |
| Gate | `auth.py` | `MCPGateMiddleware`: 401 + RFC 9728 pointer, 403 for a forced password change, viewer resolution. |
| Tools | `tools/`, `toolkit.py` | `echo` and `user_directory` as worked examples: `@public_tool()` / `@require_perm(...)` write the audit row. |
| Audit | `audit.py` | MCP events on the identity package's `audit_logs` (viewer + agent + outcome). |
| Transports | `transport.py`, `__main__.py` | `python -m cliver_playbook.app.mcp --transport stdio|http`. |
| Application | `app.py` | `create_app()` composes basic + user + mcp; `configure_runtime()` for app-less entry points. |

The `mcp:*` permission codes register themselves into the identity package's
catalog when this package is imported, so a composed install seeds them for the
admin role and a user-only install never sees them (ADR-0017).

## Install

```bash
python -m pip install -e ../cliver-playbook-app-basic  # dependency first
python -m pip install -e ../cliver-playbook-app-user
python -m pip install -e .
# or in one command: pip install -e ../basic -e ../user -e .
```

Editable installs of sibling packages coexist in one virtualenv: the
`cliver_playbook` and `cliver_playbook.app` namespace directories are
PEP 420 — deliberately no `__init__.py` — so every package's portion merges.

## Run standalone

```bash
docker compose up -d db        # or point CLIVER_DATABASE_URL at PostgreSQL
python -m cliver_playbook.app.mcp --transport http --port 8100   # full app: API + /mcp + OAuth
python -m cliver_playbook.app.mcp --transport stdio              # one stdio session on stdin/stdout
```

The default deployment is in-process: the composed application serves `/mcp`
next to the API on one port. The `stdio` transport is for agents that spawn a
process and speak JSON-RPC over pipes; with `mcp.auth_enabled` it reads the
bearer token from `MCP_BEARER_TOKEN` and refuses to start if that token is
missing, unknown or belongs to a user who must change their password.

## Migrate

No chain of its own. Apply the dependencies':

```bash
python -c "
from cliver_playbook.app.basic.alembic import run_migrations_online
from cliver_playbook.app.user.alembic import run_migrations_online as run_user
run_migrations_online(); run_user()
"
```

## Test

```bash
python -m pytest        # needs PostgreSQL; creates and drops a temp database
```

The suite binds the composed application (`create_app`) and applies both
migration chains. It includes the composition guard (no mounted sub-app, no
duplicate route, `/mcp` served as a plain route) and real-transport tests that
spawn uvicorn and stdio subprocesses against a real port and real pipes.
`tests/fixtures/app.yaml` supplies the configuration layer (pinned via
`CLIVER_CONFIG_FILE`), keeping the suite independent of the surrounding
checkout's `app.yaml`.
