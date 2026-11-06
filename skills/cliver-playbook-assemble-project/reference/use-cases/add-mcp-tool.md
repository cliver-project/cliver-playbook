# Add an MCP tool

## Use when

An agent client should call a project capability through the MCP endpoint.
The tool decorator is the enforcement and audit boundary; a bare function is
not a tool.

Profile: `mcp`.

## Do

### 1. Register the domain permission first

The tool gate is `mcp:tools:invoke` (built in) plus the domain code. Register
the domain code before the tool module imports; see
`reference/use-cases/add-backend-permission-codes.md`.

### 2. Write the tool

```python
# app/tools/orders.py
from typing import Any

from cliver_playbook.app.mcp.server import mcp
from cliver_playbook.app.mcp.toolkit import require_perm

from app.services.orders import list_orders


@mcp.tool()
@require_perm("mcp:tools:invoke", "orders:read")
async def list_recent_orders(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent orders visible to the caller."""
    rows = await list_orders(limit=limit)
    return [
        {"id": row.id, "status": row.status, "total_cents": row.total_cents}
        for row in rows
    ]
```

Decorator order matters: `@mcp.tool()` is outermost, the toolkit decorator
next. The toolkit decorator enforces the permissions, applies the concurrency
cap, writes the audit row, and records the duration.

### 3. Import the module at process start

```python
# app/tools/__init__.py
from app.tools import orders  # noqa: F401 — registers the tool
```

```python
# app/app.py
from app import tools  # noqa: F401 — before create_app() builds the routes
```

A module that is never imported is never registered. Do not register tools
inside a request handler or lazily on first call.

### 4. Return JSON-serializable data

Keep the return type small and explicit: `dict`, `list`, scalars. Do not return
SQLAlchemy models, sessions, or objects with secrets. Tool arguments should be
simple JSON types; the MCP schema is generated from the signature and
docstring.

### 5. Use the escape hatch only for diagnostics

```python
from cliver_playbook.app.mcp.toolkit import public_tool

@mcp.tool()
@public_tool()
async def ping() -> str:
    return "pong"
```

`public_tool()` is intentionally greppable and skips permission enforcement
and audit. It is for diagnostics that carry no data, not for "make it work"
gating.

## Verify

```sh
uv run uvicorn --factory app.app:create_app --port 8000
```

Open the MCP playground (or use an MCP client) at the configured mount path
(`/mcp` by default). The tool list contains the new name. Call it with a viewer
that holds both codes (success), then without `orders:read` (denied). Confirm
an audit row records the call. Run the package's tool tests for the same path:

```sh
uv run pytest tests/test_mcp_tools.py
```

## Pitfalls

- A tool module imported only by a test is not registered in production.
- `require_perm` is AND: every named code must be held. Name the tool gate and
  the domain code deliberately.
- The MCP session manager must be entered in the lifespan. Without it `/mcp`
  answers with a `RuntimeError` instead of half-working.
- Do not print or log request arguments that may contain credentials; the
  audit layer records the call metadata, not secrets.
- The built-in `echo` and `user_directory` tools are examples; do not build
  the product's tool set on them.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-mcp/src/cliver_playbook/app/mcp/toolkit.py`
  — `require_perm`, `public_tool`, audit/concurrency wrappers.
- `var/playbook/packages/backend/cliver-playbook-app-mcp/src/cliver_playbook/app/mcp/server.py`
  — the `mcp` server object.
- `var/playbook/packages/backend/cliver-playbook-app-mcp/src/cliver_playbook/app/mcp/tools/`
  — worked tools.
- Deep dive: `reference/decision-guide.md` section "Project MCP tools".
