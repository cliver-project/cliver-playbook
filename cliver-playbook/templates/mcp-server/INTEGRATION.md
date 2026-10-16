# mcp-server — integration manifest

How this template relates to `templates/user-management`: it IS the
user-management template plus the MCP-server delta below, as one complete
runnable app. The `add-mcp-server` skill applies this manifest to a project
that already has user-management — copying every ADD, applying every REPLACE,
and checking each EDIT trigger. Relative paths are template-root-relative
(`backend/…`, `frontend/…`).

Rule of thumb for REPLACE files: they are strict supersets of the
user-management version — everything UM had is still there, the MCP surface is
added around it. When the target project has already diverged, the skill must
three-way compare (UM ↔ template ↔ target) and replay the MCP additions onto
the target's version instead of overwriting it.

Prerequisite: `mcp>=2.2,<3` and `httpx2` (dev only) are ALREADY in the
user-management `pyproject.toml` (its OAuth 2.1 routes use the SDK's
request/response models). This template changes neither `pyproject.toml` nor
`package.json`, and `backend/tests/conftest.py` is byte-identical — MCP tests
toggle `settings.mcp.auth_enabled` in-process instead of via fixtures.

## Backend — ADD

| File | Contents |
|---|---|
| `backend/app/mcp/__init__.py` | Package docstring (what the module owns vs. borrows) + re-export of `register`. |
| `backend/app/mcp/server.py` | The `MCPServer` singleton (`SERVER_NAME = "cliver-app-mcp"`) and its client-visible `instructions` string. |
| `backend/app/mcp/subapp.py` | `build_mcp_subapp()` — builds the SDK `streamable_http_app()` once per process (path = `settings.mcp.mount_path`, `stateless_http=True`, DNS-rebinding protection off), then wraps the SDK route's ASGI app with the auth gate in place. A second build would orphan the first session manager, hence the memoized singleton. |
| `backend/app/mcp/auth.py` | `MCPGateMiddleware` — always in the chain, reads `settings.mcp.auth_enabled` per request. OFF binds an `AnonymousViewer`; ON verifies the bearer via UM's `verify_bearer` + `load_viewer` (same `auth_tokens` table, same revocation path), 403s `must_change_password`, and answers rejections with RFC 9728 `WWW-Authenticate` + an `mcp.auth.reject` audit row. Also `resolve_viewer()` (shared with stdio). |
| `backend/app/mcp/context.py` | ContextVars `current_viewer` / `current_agent` / `current_request`; `AnonymousViewer` (fail-closed `has()`); `AgentIdentity` + `build_agent_identity()` (the single whitelist + truncation implementation, fed by HTTP headers or `MCP_AGENT_TYPE`/`MCP_AGENT_ID` env vars). |
| `backend/app/mcp/audit.py` | `write_tool_audit()` / `write_auth_rejection()` — thin wrappers over UM's `write_audit` writing `mcp.tools.call` / `mcp.prompts.get` / `mcp.resources.read` / `mcp.auth.reject` rows with the agent fields from the request context. Best-effort: an audit failure is logged, never allowed to break the call. |
| `backend/app/mcp/permissions.py` | `MCP_PERMISSION_CODES` re-export of the four `mcp:*` catalog codes, so seeds/tests/gate reference them symbolically. |
| `backend/app/mcp/toolkit.py` | `@public_tool()` / `@require_perm(...)` decorators (nested under `@mcp.tool()`): per-call timing, exactly one audit row, permission enforcement (all codes, checked fresh), and a process-wide concurrency semaphore. `functools.wraps` preserves `__wrapped__` so the SDK's schema generation sees the real signature. |
| `backend/app/mcp/tools/__init__.py` | `register_default_tools()` — idempotent import-for-side-effect of the built-in tool modules. |
| `backend/app/mcp/tools/echo.py` | The public-tool exemplar and identity probe: reports the resolved viewer, agent headers and transport — the connectivity check an agent calls first. |
| `backend/app/mcp/tools/user_directory.py` | The permission-gated exemplar: `@require_perm("mcp:tools:invoke", "user:read")`, own DB session, shared service layer (`list_users`), compact model-friendly payload. The shape every real business tool follows. |
| `backend/app/mcp/api.py` | The MCP module's `/api/v1` routes: `GET /mcp/info` (public discovery: server name, mount path, auth flag) and `GET /mcp/calls` (MCP-scoped audit listing, gated `mcp:agents:read`, filters `event LIKE 'mcp.%'` server-side). |
| `backend/app/mcp/transport.py` | `run_stdio()` / `run_http()` — the two standalone shapes. stdio binds scope+agent+viewer once before the transport starts (fail fast when auth is on and `MCP_BEARER_TOKEN` is missing/invalid/`must_change_password`); http serves the FULL parent app (API + MCP + OAuth) with uvicorn on a dedicated port. |
| `backend/app/mcp/__main__.py` | `python -m app.mcp --transport {stdio,http} --host --port` entry (argv parsing and dispatch only). Used by `make mcp-stdio` / `make mcp-http`. |
| `backend/alembic/versions/0003_mcp_server.py` | Structural no-op anchor on `0002_user_management`. No new tables in v1 — audit and tokens reuse UM's; the revision exists so future MCP-owned tables have a chain home. |
| `backend/tests/test_mcp_structural.py` | 13 tests: catalog extension, viewer/agent accessor behaviour, truncation, audit-row shape (incl. the logger-survives-alembic regression), server singleton name. |
| `backend/tests/test_mcp_gate.py` | 8 tests: OFF mode binds anonymous; ON missing/unknown/expired token 401s with RFC 9728 header; `must_change_password` 403; rejection audit rows with agent fields; non-`/mcp` paths untouched. |
| `backend/tests/test_mcp_subapp.py` | 5 tests: single build per process, route path = `mount_path`, gate wrapped in place, SDK layout regression guard. |
| `backend/tests/test_mcp_tools.py` | 7 tests: `echo` in all three identity states; `user_directory` permission matrix (both codes enforced); signature preservation; `ToolError` on denial; audit rows for success and denial. |
| `backend/tests/test_mcp_audit.py` | 2 tests: audit wrapper writes the expected JSONB detail (agent + args truncation) and survives a broken DB. |
| `backend/tests/test_mcp_permissions.py` | 2 tests: `require_perm` denies with `ToolError` when the code is missing; anonymous viewer denies everything. |
| `backend/tests/test_mcp_transports.py` | 9 tests: real-port streamable-http (initialize / tools list / call, auth ON and OFF) and a real `python -m app.mcp --transport stdio` subprocess (initialize / call / refusal without `MCP_BEARER_TOKEN`). |
| `backend/tests/test_mcp_api.py` | 5 tests: `/mcp/info` public + settings-tracked; `/mcp/calls` permission separation (`audit:read` ≠ `mcp:agents:read`), anonymous 401, newest-first ordering, pagination + 422. |

## Backend — REPLACE (user-management-owned files, strict supersets)

| File | What changed vs user-management |
|---|---|
| `backend/app/main.py` | Adds the lifespan composition (`_mcp_subapp.router.lifespan_context(_mcp_subapp)` inside the parent's `lifespan`), the `mcp_register(app)` seam, and `app.mount("/", _mcp_subapp)` AFTER the API routers (Starlette matches in order, so every `/api/v1/*` route wins first). The OAuth 2.1 root mount stays exactly as UM's — `mount_oauth_routes` prepends to `app.router.routes`, so it still wins over the sub-app's catch-all. |
| `backend/app/core/config.py` | Adds the nested `mcp: McpSettings` block (`auth_enabled` default false, `mount_path` with a no-trailing-slash validator, `max_concurrent_calls`, `agent_type_whitelist` incl. `web-playground`, `agent_id_max_length`). Deliberately has NO MCP OAuth sub-block: the surface reuses the Web's `oauth21_*` settings, whose PRM already names `{base}/mcp` as the resource. UM blocks are untouched. |

## Frontend — ADD

| File | Contents |
|---|---|
| `frontend/src/api/mcp.ts` | The MCP JSON-RPC client: `rpc()` posts to the MCP endpoint with `Accept: application/json, text/event-stream` (the transport 406s otherwise) and parses both JSON and SSE (`data:` line) replies; `listMcpTools` / `callMcpTool` for the playground; `listMcpCalls` for the agents view; `fetchMcpInfo` + `transportErrorMessage` (reads the RFC 9728 `{error, error_description}` body). |
| `frontend/src/pages/MCPPlaygroundPage.tsx` | `/mcp/playground` (gated `mcp:tools:invoke`): endpoint card (URL + copy + auth badge + `claude mcp add` hint), tool picker over live `tools/list`, JSON args editor, call/result panel (ok vs tool-error, duration, structured content), and a recent-calls strip (display-gated on `mcp:agents:read`). |
| `frontend/src/pages/admin/MCPAgentsPage.tsx` | `/mcp/agents` (gated `mcp:agents:read`): agent summary grouped by `agent_type` (calls / failures / last seen) plus the recent-activity table (agent, user, tool, outcome, duration, args). |
| `frontend/src/components/mcp/AgentBadge.tsx` | Agent-type badge (recognized types vs `unknown`). |
| `frontend/src/components/mcp/CopyButton.tsx` | Clipboard button with success/error toasts. |
| `frontend/src/components/ui/textarea.tsx` | Vendored shadcn/ui primitive (matches the existing vendored-component conventions; no new dependency). |

## Frontend — REPLACE (user-management-owned files, strict supersets)

| File | What changed vs user-management |
|---|---|
| `frontend/src/App.tsx` | Adds the two MCP routes inside `AppLayout`, permission-gated the same way the admin pages are. |
| `frontend/src/layouts/AppLayout.tsx` | Adds the playground / agents nav items (permission-gated). |
| `frontend/src/locales/en.json` | Adds `nav.mcpPlayground` / `nav.mcpAgents` + the whole `mcp.*` tree (common/playground/agents). UM keys untouched. |
| `frontend/src/locales/zh.json` | Same keys, Chinese. |
| `frontend/vite.config.ts` | Adds the `/mcp` dev proxy (the MCP endpoint lives outside `/api/v1`; keep it in sync if `mcp.mount_path` changes). |

## Root — REPLACE

| File | What changed vs user-management |
|---|---|
| `app.yaml` | Appends the `mcp:` block (auth_enabled / mount_path / max_concurrent_calls / agent_type_whitelist / agent_id_max_length). No MCP OAuth block — see config.py row. |
| `.env.example` | Appends the MCP section, including the note that `MCP_BEARER_TOKEN` / `MCP_AGENT_TYPE` / `MCP_AGENT_ID` are read from the PROCESS environment (stdio bootstrap), NOT from `.env`. |
| `Makefile` | Adds `MCP_HTTP_PORT`, the `##@ MCP server` section, and the `mcp-stdio` / `mcp-http` targets (separate processes against the same DB). |

## EDIT

| File | Edit |
|---|---|
| `backend/app/auth/permissions.py` | Append the four `mcp:*` codes (`mcp:tools:invoke`, `mcp:prompts:get`, `mcp:resources:read`, `mcp:agents:read`) to `PERMISSION_CATALOG`, group `"MCP"`. This is the template's ONLY source edit: the catalog cannot be extended at runtime (its codes are imported by value into `dependencies` / `services.roles`), so the delta is static by design. The admin role picks the codes up from the seed on fresh databases; on an existing database grant them to the admin role (or any role that should call MCP tools) via the roles UI. |

Alembic chain: `0003_mcp_server` hangs off `0002_user_management`
(`down_revision` fixed). In a project whose chain has diverged, adjust
`down_revision` to the current head (or `alembic merge`) instead.

Note for projects copied from an OLDER template: `backend/alembic/env.py`
must pass `disable_existing_loggers=False` to `fileConfig` — the default
`True` silently disables every already-created logger, which breaks the MCP
suite's audit-logger regression in-process. All current templates ship the
fix; older copies need the one-line change (see the file's comment).

## Post-copy checklist

1. `cd backend && uv sync` — no new dependencies (`mcp` + `httpx2` came with
   user-management).
2. `uv run alembic upgrade head` — lands on `0003_mcp_server` (structural
   no-op; the chain anchor only).
3. `uv run pytest` — 138 tests (87 user-management + 51 MCP), all
   offline-capable except the DB (needs the compose PostgreSQL).
4. `cd frontend && pnpm install && pnpm build` — no new dependencies.
5. Manual, auth OFF (template default): `make backend-start` →
   `curl -i -X POST http://127.0.0.1:8000/mcp` → a protocol error, not 401
   (the endpoint answers); playground page lists tools and `echo` succeeds
   anonymously; `user_directory` returns a tool error (permission denied —
   this is the design, see the page's warning banner).
6. Manual, auth ON: set `CLIVER_MCP__AUTH_ENABLED=true`, restart. `/mcp`
   without a token → 401 + `WWW-Authenticate` pointing at
   `/.well-known/oauth-protected-resource`; with a Web session token
   (playground does this automatically) → calls run as that user and
   `user_directory` works for an admin. Both outcomes appear on `/mcp/agents`
   grouped under `web-playground`.
7. Manual, stdio: `MCP_AGENT_TYPE=claude-code make mcp-stdio` and speak
   JSON-RPC over stdin (or point a CLI agent at the command). With auth on,
   export `MCP_BEARER_TOKEN` first — without it the process refuses to start.

## Not included (deliberate)

- A generic audit-log module (JSONB payload + record API + viewer UI) — the
  MCP surface writes into UM's existing `audit_logs` on purpose; a richer
  audit module is a separate template.
- MCP without user-management — the surface is a consumer of UM's identity
  (tokens, viewer, permissions, audit); there is no degraded standalone
  variant.
- Prompts / resources — the registration helpers exist and the audit wrapper
  understands them, but no built-in examples ship; add per project.
- File downloads / export-retention plumbing — out of scope for the template;
  add per project with its own storage story.
