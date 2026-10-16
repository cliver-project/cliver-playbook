# cliver-app (mcp-server)

The service scaffold plus the **identity domain** plus the **MCP server**:
RBAC, multi-provider OIDC, OAuth 2.1 provider, an MCP server
(streamable-http + stdio) at `/mcp` with first-class auth and audit, and a
viewer UI for both — one complete runnable app. See `INTEGRATION.md` for the
exact delta against `templates/user-management`.

The MCP server is the entry point for AI agents (Claude Code, WorkBuddy,
Codex, custom clients). It runs in the same process as the Web backend by
default (lifespan-composed Starlette sub-app at `/mcp`); stdio transport is
also supported as a separate process via `make mcp-stdio`.

## What you get beyond the user-management template

- **MCP server (streamable-http + stdio)**: the official `mcp>=2.2,<3` SDK
  (`MCPServer` + `streamable_http_app` / `stdio_server`), a sub-app mounted
  at `/mcp`, its lifespan composed into the parent FastAPI. stdio is a
  separate process (`make mcp-stdio`, or `make mcp-http` for a sidecar on
  its own port) sharing the same database.
- **Auth gate, ON/OFF**: `CLIVER_MCP__AUTH_ENABLED` (default OFF). With
  auth ON, every `/mcp` request must carry a bearer that resolves through
  the **same `auth_tokens` table the Web uses** (no separate `mcp_tokens`
  table) into the **same `Viewer`** the Web's `get_current_user` builds — so
  Web permission rules apply to agents unchanged, and a Web force-logout or
  password change revokes an agent's token as a side effect. With auth OFF,
  calls run under an **anonymous viewer**: public tools answer,
  permission-gated tools are denied — auth off never silently grants
  permissions.
- **Agent identification**: callers send `X-MCP-Agent-Type` (`claude-code` /
  `workbuddy` / `codex` / … — whitelist in `app.yaml`) and
  `X-MCP-Agent-Id` (a stable per-install id); stdio uses `MCP_AGENT_TYPE` /
  `MCP_AGENT_ID`. Every audit row records both next to the authenticated
  viewer (or null), so one log view answers "who called what, from which
  agent, with which token identity".
- **Audit**: writes to the same `audit_logs` table user-management owns — no
  second table, no parallel pipeline. Each tool call lands a row
  (`mcp.tools.call`; the wrapper understands `mcp.prompts.get` /
  `mcp.resources.read` too) with sanitized args, ok/error and duration.
  Gate rejections land `mcp.auth.reject` rows **including the agent headers**,
  so failed probes leave a trail of which machine tried.
- **One OAuth 2.1 provider for everything**: the user-management provider
  (`app/auth/oauth21.py`) is reused as-is — its protected-resource metadata
  already names `{base}/mcp` as the resource, and the gate's 401
  `WWW-Authenticate` header points agents at it. No MCP-scoped copy, no
  `mount_path` parameter, nothing to keep in sync.

## Quickstart

```bash
make init                   # backend (uv) + frontend (pnpm) dependencies
make backend-start          # starts db container, migrates, serves :8000
make web-ui-start           # serves http://127.0.0.1:5173 (proxies /api and /mcp)
# MCP is at http://127.0.0.1:8000/mcp by default (auth OFF).

# Turn auth on (recommended for any non-loopback deployment) — then /mcp
# calls must carry a Bearer token from the auth_tokens table. Any Web
# session token works; the Web's playground page attaches yours
# automatically, and the OAuth 2.1 provider can hand out long-lived ones.
echo "CLIVER_MCP__AUTH_ENABLED=true" >> .env

# stdio transport (separate process, same DB):
MCP_AGENT_TYPE=claude-code make mcp-stdio
```

First login: same as user-management — `admin` / your
`CLIVER_INITIAL_ADMIN_PASSWORD` (or the random password the migration printed
once) — forced password change on first login.

Verify:

```bash
curl http://127.0.0.1:8000/api/v1/health              # {"status":"ok"}
curl http://127.0.0.1:8000/api/v1/mcp/info            # server name + auth flag
curl -i -X POST http://127.0.0.1:8000/mcp             # 406 without the Accept header / protocol error — the endpoint answers
make backend-test                                     # 138 tests
pnpm --dir frontend build                             # type-check + production build
```

In the browser: **MCP 试调台 / MCP playground** (`/mcp/playground`) speaks the
real wire protocol with your session token; **MCP Agent** (`/mcp/agents`)
groups recent calls by agent type.

## Layout (mcp delta over user-management)

```
backend/
  app/mcp/                      # the MCP delta
    __init__.py                 #   package docstring + register re-export
    module.py                   #   register(app): API routes + tool registration
    server.py                   #   MCPServer singleton + instructions
    subapp.py                   #   build_mcp_subapp(): streamable_http_app + in-place gate wrap
    auth.py                     #   MCPGateMiddleware (reads auth_enabled per request)
    context.py                  #   ContextVars: viewer / agent / request + AnonymousViewer
    audit.py                    #   write_tool_audit(); thin wrapper over user-management's write_audit
    toolkit.py                  #   @public_tool / @require_perm decorators (timing + audit + perms + cap)
    permissions.py              #   re-export of the 4 mcp:* catalog codes
    api.py                      #   GET /api/v1/mcp/info + /api/v1/mcp/calls
    transport.py                #   run_stdio() / run_http()
    __main__.py                 #   python -m app.mcp --transport {stdio,http}
    tools/
      echo.py                   #   public-tool exemplar + identity probe
      user_directory.py         #   permission-gated exemplar (viewer → perms → service → audit)
  app/main.py                   # REPLACE: lifespan composition + mount("/", subapp) after the routers
  app/core/config.py            # REPLACE: nested mcp: block (auth_enabled, mount_path, whitelist, …)
  app/auth/permissions.py       # EDIT: the 4 mcp:* codes appended to the static catalog
  alembic/versions/
    0003_mcp_server.py          # structural no-op anchor (audit + tokens reuse UM tables)
frontend/
  src/api/mcp.ts                # JSON-RPC client (dual JSON/SSE parsing, RFC 9728 error bodies)
  src/pages/MCPPlaygroundPage.tsx   # /mcp/playground — call tools with your own token
  src/pages/admin/MCPAgentsPage.tsx # /mcp/agents — recent activity grouped by agent
  src/components/mcp/           # AgentBadge, CopyButton
  src/components/ui/textarea.tsx    # vendored shadcn primitive (no new dependency)
```

## Adding a tool

```python
# app/mcp/tools/my_tool.py
from app.mcp.server import mcp
from app.mcp.toolkit import require_perm   # or public_tool

@mcp.tool()
@require_perm("mcp:tools:invoke", "user:read")
async def my_tool(q: str = "") -> dict:
    """One-line description the model reads when picking tools."""
    ...  # open your own DB session; call the shared service layer
```

Then import it in `app/mcp/tools/__init__.py`'s `register_default_tools()`.
The decorators own timing, the audit row and permission enforcement — a bare
`@mcp.tool()` function would be invisible in the audit trail.

## Conventions (MCP-specific)

- **Auth tokens live in `auth_tokens`**, not a separate `mcp_tokens` table.
  Web force-logout and password change revoke them as a side effect — that
  is the point of the design, not a wart.
- **Viewer is the same dataclass** the Web's `get_current_user` produces:
  `viewer.permissions` (a `frozenset[str]`) + `viewer.has(code)`. The MCP
  decorator reuses it; there is no parallel permission system.
- **"Auth off" ≠ "all tools free"**: it means "no token required to call
  tools that do not ask for a permission". `@require_perm` tools are denied
  for the anonymous viewer — permission is a separate dimension from
  authentication, and the gate enforces both.
- **stdio identity plumbing**: token from `MCP_BEARER_TOKEN`, agent type
  from `MCP_AGENT_TYPE`, agent id from `MCP_AGENT_ID` — the env-variable
  equivalents of the HTTP headers. These are read from the process
  environment, **not** from `.env` (an agent hands env to its child process;
  `.env` is app config). With auth on, a missing token refuses startup —
  the per-request 401 has no mid-stream equivalent.
- **Lifespan composition is the seam**: `subapp.router.lifespan_context(subapp)`
  is driven by the parent FastAPI's `lifespan` (spike-verified against mcp
  2.3.0). The SDK registers its session manager on the server singleton as a
  build side-effect, so `build_mcp_subapp()` is memoized — build it twice
  and the first manager is orphaned.
- **Audit is best-effort by design**: an audit-write failure is logged at
  WARNING and swallowed; a transient DB hiccup must not fail an otherwise
  successful tool call.
- **Contract changes break agents**: tool names, argument names and the
  `instructions` string are the model-facing interface. Treat renames as
  breaking changes, the way you would an HTTP API path.

## Why this design (one paragraph for the reviewer)

The MCP server is a *consumer* of user-management infrastructure, not a peer
that re-implements it. Auth, RBAC, audit and OAuth 2.1 all funnel through
UM's existing tables and helpers. MCP owns only the tool/prompt/resource
definitions, the transport plumbing, the gate middleware, and the
agent-identification fields on audit rows. That makes "turn auth on" a
one-line config change with no migration, and "revoke an agent" an action
that already exists in the Web UI (force-logout, password change, OAuth grant
revocation).
