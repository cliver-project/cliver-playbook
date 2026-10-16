# cliver-app (mcp-server)

The service scaffold plus the **identity domain** plus the **MCP server**:
RBAC, multi-provider OIDC, OAuth 2.1 provider, an MCP server (streamable-http
+ stdio) at `/mcp` with first-class auth and audit, and a viewer UI for both
— one complete runnable app. See `INTEGRATION.md` for the exact delta against
`templates/user-management`.

The MCP server is the entry point for AI agents (WorkBuddy, Codex, Claude
Code, custom clients). It runs in the same process as the Web backend by
default (lifespan-composed Starlette sub-app at `/mcp`); stdio transport
is also supported as a standalone process via `make mcp-stdio`.

## What you get beyond the user-management template

- **MCP server (streamable-http + stdio)**: the official `mcp>=2.2,<3` SDK
  (`MCPServer` + `streamable_http_app` / `stdio_server`), a sub-app mounted
  at `/mcp`, lifespan composed into the parent FastAPI. stdio is a
  separate process started by `make mcp-stdio` against the same DB and
  the same `DATABASE_URL`.
- **Auth gate, ON/OFF**: `CLIVER_MCP__AUTH_ENABLED` (default OFF in dev).
  ON routes every `/mcp` request through the gate, which decodes the
  bearer against the **same `auth_tokens` table the Web uses** (no
  separate `mcp_tokens` table) and produces the **same `Viewer`
  dataclass** the Web's `get_current_user` produces — so `require_perm`
  works identically for HTTP and MCP calls. Web's `force-logout` /
  `change-password` revoke MCP tokens as a side effect.
- **Agent identification**: every MCP request carries `X-MCP-Agent-Type`
  (`claude-code` / `workbuddy` / `codex` / `mcp-cli` / `unknown` /
  configured-allowlist) and `X-MCP-Agent-Id` (a stable per-install id;
  empty = anonymous). The audit row records both alongside the
  authenticated viewer (or `None` when auth is off), so a single log
  view answers "who called what, from which agent, with which token
  identity".
- **Audit**: writes to the same `audit_logs` table user-management owns.
  No second table, no parallel pipeline. Every tool / prompt / resource
  call lands a row with `event="mcp.tool.call"` (or `mcp.prompt.get` /
  `mcp.resource.read`), the viewer (or `None`), the agent type + id,
  sanitized args, ok/error, duration.
- **OAuth 2.1 over the same provider**: the user-management OAuth 2.1
  server (`app/auth/oauth21.py`) is reused, mounted at `/mcp/oauth`
  (not at the root), so the MCP client's AS/PRM discovery never
  collides with the Web's. The `mount_path` parameter is added to the
  existing `mount_oauth_routes(app, ...)` with `""` as the default —
  UM behavior is unchanged.

## Quickstart

```bash
make init                   # backend (uv) + frontend (pnpm) dependencies
make backend-start          # starts db container, migrates, serves :8000
make web-ui-start           # serves http://127.0.0.1:5173 (proxies /api to :8000)
# MCP is at http://127.0.0.1:8000/mcp by default (auth OFF).

# Turn auth on (recommended for any non-loopback deployment):
echo "CLIVER_MCP__AUTH_ENABLED=true" >> .env
# Re-issue a long-lived bearer token through the Web admin or by direct
# DB insert; pass it as `Authorization: Bearer ...` on /mcp calls.

# stdio transport (separate process, same DB):
make mcp-stdio
```

First login: same as user-management — `admin` / your
`CLIVER_INITIAL_ADMIN_PASSWORD` (or the random password the migration
printed once) — forced password change on first login.

Verify:

```bash
curl http://127.0.0.1:8000/api/v1/health              # {"status":"ok"}
curl http://127.0.0.1:8000/mcp                       # 405 or 200 — MCP mounted
make backend-test                                     # tests pass
pnpm --dir frontend build                             # type-check + production build
make mcp-stdio                                        # boots stdio process
```

## Layout (mcp delta over user-management)

```
backend/
  app/mcp/                      # the MCP delta
    server.py                   #   MCPServer singleton + tool/prompt/resource registration
    subapp.py                   #   build_mcp_subapp(): streamable_http_app + ASGI gate wrapper
    transport.py                #   serve_stdio() / serve_http() dispatch
    standalone.py               #   python -m app.mcp --transport {stdio,http} entry
    auth.py                     #   MCPGateMiddleware (only mounted when auth_enabled)
    audit.py                    #   write_tool_audit(); thin wrapper over user-management's write_audit
    context.py                  #   ContextVars: current_viewer / current_agent / current_request
    permissions.py              #   MCP's PERMISSION_CATALOG (mcp:tools:invoke, mcp:prompts:get, ...)
    tools/
      echo.py                   #   minimal public-tool demo
      user_directory.py         #   real-business tool: viewer + permission + agent + audit
  app/main.py                   # REPLACE: lifespan composition + app.mount("/mcp", subapp)
  app/auth/oauth21.py           # EDIT: mount_oauth_routes(app, mount_path="") gains mount_path param
  alembic/versions/
    0003_mcp_server.py          # 0003 migration: nothing structural (auth_tokens is reused)
frontend/
  src/api/mcp.ts                # typed wrappers (listTransports / rotateStaticToken / listToolAudit)
  src/pages/MCPPlaygroundPage.tsx  # online tool playground (transport select + token + call)
  src/pages/admin/MCPAgentsPage.tsx # recent tool calls grouped by agent
  src/components/mcp/           # AgentBadge, CopyTokenButton, etc.
```

## Conventions (MCP-specific)

- **Auth tokens live in `auth_tokens`**, not in a separate `mcp_tokens`
  table. Web's `force-logout` and password change revoke them as a side
  effect — this is the point of the design, not a wart.
- **Viewer is the same dataclass** the Web's `get_current_user`
  produces: `viewer.user_id`, `viewer.client_id`, `viewer.permissions`
  (a `frozenset[str]`), `viewer.has(code)`. MCP's `require_perm(code)`
  decorator reuses it; no parallel permission system.
- **Tool decorator is the official SDK's** (`@server.tool(...)`) — no
  custom wrapper. Audit + permission gating is done in the *function
  body* the way ai-gov's `mcp_server/tools.py` does it (the SDK has no
  middleware hook in 2.x).
- **`@public_tool()` for the rare tool that should work without auth.**
  Default is the opposite: even with `auth_enabled: false`, a tool
  that declares `@require_perm("...")` is rejected — "auth off" is
  not "all tools free", it's "no token required to call tools that
  don't ask for a permission".
- **stdio's identity plumbing**: token from `MCP_BEARER_TOKEN` env
  var, agent type from `MCP_AGENT_TYPE`, agent id from `MCP_AGENT_ID`.
  These mirror the HTTP headers exactly.
- **Lifespan composition is the seam**: `subapp.router.lifespan_context(subapp)`
  is driven by the parent FastAPI's `lifespan` context manager (spike
  verified 2026-10-16 against mcp 2.3.0). When the MCP server runs
  standalone (stdio), the same `serve_stdio()` builds its own
  `MCPServer` and runs it directly.

## Why this design (one paragraph for the reviewer)

The MCP server is a *consumer* of user-management infrastructure, not a
peer that re-implements it. Auth, RBAC, audit, and OAuth 2.1 all
funnel through UM's existing tables and helpers. The only things MCP
owns are the tool/prompt/resource definitions, the transport
plumbing, the gate middleware, and the agent-identification fields on
audit rows. This makes "turn auth on" a one-line config change with
no migration, and makes "rotate an MCP bearer" a one-line admin
action that already works in the Web's OAuth clients page.
