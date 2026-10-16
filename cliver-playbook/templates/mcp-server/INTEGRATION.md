# mcp-server — integration manifest

How this template relates to `templates/user-management`: it IS the
user-management template plus the MCP-server delta below, as one
complete runnable app. The `add-mcp-server` skill (Phase 4) will apply
this manifest to a UM-derived project — copying every ADD, applying
every REPLACE, and checking each EDIT trigger. Relative paths are
template-root-relative (`backend/…`, `frontend/…`).

This template is the third in the sequence:
- `service-scaffold` → `user-management` → **mcp-server** (this one).
- The mcp-server cannot be composed without user-management; every
  line below assumes UM is present.
- All UM conventions (RBAC, audit, OAuth 2.1, must-change-password
  gate, OIDC identity linking) carry over unchanged.

The MCP server is a *consumer* of UM infrastructure, not a peer that
re-implements it: auth, RBAC, audit, and OAuth 2.1 all funnel through
UM's existing tables and helpers. The only things MCP owns are the
tool/prompt/resource definitions, the transport plumbing, the gate
middleware, and the agent-identification fields on audit rows.

## What you get

- **streamable-http** mounted at `/mcp` on the parent FastAPI app
  (lifespan-composed Starlette sub-app), and **stdio** as a separate
  process started by `make mcp-stdio`. Both transports share the
  same `MCPServer` instance, the same tools, and the same DB.
- **Auth ON/OFF** via `CLIVER_MCP__AUTH_ENABLED` (default OFF in
  dev). ON: every `/mcp` request must carry a bearer from the
  user-management `auth_tokens` table; the gate reuses UM's
  `verify_bearer` + `load_viewer` and binds the result to a
  `ContextVar` for the duration of the request.
- **Agent identification** via `X-MCP-Agent-Type` and
  `X-MCP-Agent-Id` headers (HTTP) or `MCP_AGENT_TYPE` /
  `MCP_AGENT_ID` env vars (stdio). The audit row records both
  alongside the authenticated viewer.
- **Audit**: writes to the same `audit_logs` table UM owns. No
  second table, no parallel pipeline. Event names:
  `mcp.tool.call` / `mcp.prompt.get` / `mcp.resource.read`.
- **OAuth 2.1 over UM's provider**, mounted at `/mcp/oauth` (not
  the root) so MCP client AS/PRM discovery never collides with the
  Web's. The `mount_oauth_routes(app, mount_path=...)` parameter is
  the single EDIT in UM's `app/auth/oauth21.py`.

## How this manifest is organized

The rest of this file enumerates the MCP-server delta over the
user-management template. It uses the same ADD / REPLACE / EDIT
convention as `templates/user-management/INTEGRATION.md`.

(Final counts and section bodies will be filled in as M1–M9 land.
The skeleton below shows where each piece of the delta belongs.)

## Backend — ADD

| File | Contents |
|---|---|
| `backend/app/mcp/__init__.py` | Module docstring + `register(app)` (no side-effects at import time). |
| `backend/app/mcp/server.py` | Module-level `MCPServer` instance; `register_tool` / `register_prompt` / `register_resource` thin wrappers that also bind audit + permission metadata. |
| `backend/app/mcp/subapp.py` | `build_mcp_subapp()` — returns a Starlette sub-app ready to be mounted on the parent FastAPI at `settings.mcp.mount_path`. Composes lifespan; conditionally wraps the `MCPGateMiddleware`. |
| `backend/app/mcp/transport.py` | `serve_stdio()` / `serve_http()` — dispatch used by the standalone entry point and by tests. |
| `backend/app/mcp/standalone.py` | `python -m app.mcp` entry: parses `--transport {stdio,http}` / `--port` / `--host`, calls into `transport.py`. |
| `backend/app/mcp/auth.py` | `MCPGateMiddleware` — only mounted when `settings.mcp.auth_enabled` is true. Calls UM's `verify_bearer` + `load_viewer`; binds `Viewer` to a ContextVar. |
| `backend/app/mcp/audit.py` | `write_tool_audit()` — thin wrapper over UM's `write_audit`, adding `event="mcp.tool.call"` (or prompt / resource) and the agent_* fields extracted from the current request. |
| `backend/app/mcp/context.py` | `current_viewer()` / `current_agent()` / `current_request()` ContextVar accessors + helpers to set them at the gate. |
| `backend/app/mcp/permissions.py` | MCP's `PERMISSION_CATALOG` (codes `mcp:tools:invoke` / `mcp:prompts:get` / `mcp:resources:read` / `mcp:agents:read`). Composed into the global catalog at registration time so `require_perm` rejects unknown codes at decoration. |
| `backend/app/mcp/tools/__init__.py` | `register_default_tools(server)` — adds the built-in `echo` and `user_directory` tools (and any future built-ins). |
| `backend/app/mcp/tools/echo.py` | The minimal public-tool demo. |
| `backend/app/mcp/tools/user_directory.py` | The real-business demo: viewer + `user:read` permission + agent + audit, queries UM's `users` table. |
| `backend/app/mcp/module.py` | The `register(app)` entry point called by the parent `main.py`. |
| `backend/alembic/versions/0003_mcp_server.py` | No structural changes; the migration exists so MCP's down-revision chain is anchored to a revision the user can roll back to, and as the natural home for future MCP-owned tables. |
| `backend/tests/test_mcp_auth.py` | Auth gate: OFF-pass / ON-401+RFC9728 / 401-audit / 401-WWW-Authenticate / token-revoked. |
| `backend/tests/test_mcp_audit.py` | Audit: tool success / tool failure / prompt / resource / off-auth viewer=None but agent recorded / agent_type whitelist enforcement. |
| `backend/tests/test_mcp_transports.py` | Transport: streamable_http initialize+tools.list+echo (real port) / stdio via subprocess (line-delimited JSON validation). |
| `backend/tests/test_mcp_permissions.py` | Permissions: viewer missing code → ToolError / off-auth public-tool works / off-auth perm-required tool rejected. |

## Backend — REPLACE (UM-owned files, strict supersets)

| File | What changed vs UM |
|---|---|
| `backend/app/main.py` | Adds a `lifespan` that enters `subapp.router.lifespan_context(subapp)`; mounts the MCP subapp at `settings.mcp.mount_path`. The `mcp` settings block drives both. UM's auth/admin/items/meta routers and middleware are unchanged. |
| `backend/app/core/config.py` | Adds the nested `mcp: McpSettings` block (mount_path, auth_enabled, max_concurrent_calls, agent_type_whitelist, agent_id_max_length, oauth.*) and a `settings.mcp` accessor. UM blocks are untouched. |
| `backend/app/models/entities.py` | **No changes** — MCP writes to UM's `audit_logs`; it owns no new tables in v1. The `McpAuditLog` table some prior MCP implementations carried is intentionally NOT introduced here. |
| `backend/pyproject.toml` | Adds `httpx2` (mcp 2.x client dev-only dep for tests). `mcp>=2.2,<3` was already added by the UM template. |
| `backend/tests/conftest.py` | Adds an `auth_enabled` fixture (env-mutates `CLIVER_MCP__AUTH_ENABLED`, restores on teardown). |
| `backend/tests/__init__.py` | Same as UM. |

## Backend — EDIT (UM files, small targeted change)

| File | What changes |
|---|---|
| `backend/app/auth/oauth21.py` | `mount_oauth_routes(app, mount_path: str = "")` gains a `mount_path` parameter (default `""` so UM behavior is unchanged). The MCP template's `main.py` calls `mount_oauth_routes(app, mount_path="/mcp/oauth")` so the MCP AS/PRM endpoints live under the same prefix as the MCP HTTP transport. |

## Frontend — ADD

| File | Contents |
|---|---|
| `frontend/src/api/mcp.ts` | Typed wrappers: `listTransports` / `rotateStaticToken` / `listToolAudit`. |
| `frontend/src/pages/MCPPlaygroundPage.tsx` | Online tool playground: select transport / paste a token (or leave blank when auth off) / pick a tool / call it / see the result and the audit row. |
| `frontend/src/pages/admin/MCPAgentsPage.tsx` | Recent tool calls grouped by `X-MCP-Agent-Type`; permissions-gated `mcp:agents:read`. |
| `frontend/src/components/mcp/AgentBadge.tsx` | A small chip showing the agent type + a copy-button for the id. |
| `frontend/src/components/mcp/CopyTokenButton.tsx` | Click-to-copy with a brief confirmation toast. |
| `frontend/src/locales/en.json` | Adds `nav.mcp*`, `mcp.*` keys (UM keys untouched). |
| `frontend/src/locales/zh.json` | Same keys, Chinese. |

## Frontend — REPLACE (UM-owned files, strict supersets)

| File | What changed vs UM |
|---|---|
| `frontend/src/App.tsx` | Adds `/mcp/playground` (gated `mcp:tools:invoke`) and `/mcp/agents` (gated `mcp:agents:read`); routes are inside the existing `AppLayout` and use the existing `RequirePerm` component. |
| `frontend/src/layouts/AppLayout.tsx` | Adds the two MCP nav items; the user menu gains no entry (MCP is a developer / admin surface). |
| `frontend/src/api/client.ts` | Adds an `X-MCP-Agent-Type` + `X-MCP-Agent-Id` request header source so the playground (and any future MCP-aware client code) sends them. The token-bearer interceptor is unchanged. |

## Root — REPLACE

| File | What changed vs UM |
|---|---|
| `app.yaml` | UM-prefix preserved; appends the `mcp:` block (auth_enabled / mount_path / max_concurrent_calls / agent_type_whitelist / agent_id_max_length / oauth.issuer_url / oauth.access_ttl_seconds / oauth.refresh_ttl_seconds / oauth.code_ttl_seconds). All `CLIVER_MCP__...` env vars override. |
| `.env.example` | Adds the `CLIVER_MCP__*` overrides (all commented; defaults shown). |
| `Makefile` | Adds `mcp-stdio` target. `mcp-up` / `mcp-down` are NOT added (the MCP server runs in the same process as the Web backend by default; the stdio target starts a separate process on demand). |

## EDIT (UM files in this template's tree)

The only EDIT in the UM tree is the `mount_oauth_routes` parameter
described above. Everything else is ADD-only or a strict REPLACE
superset of the UM file.

## Post-copy checklist

1. `cd backend && uv sync` — installs `httpx2` (already on UM's deps).
2. `uv run alembic upgrade head` — applies 0003 (no-op structural) and
   the chain lands at head.
3. `uv run pytest` — full suite: UM 87 + mcp ~24.
4. `cd frontend && pnpm install && pnpm build` — no new frontend deps.
5. Manual: hit `/mcp` with `curl http://127.0.0.1:8000/mcp` and
   confirm a non-error response (typically 405 GET on the MCP POST
   endpoint, which proves the subapp is mounted). Flip
   `CLIVER_MCP__AUTH_ENABLED=true` and re-test: every `/mcp` call
   should now 401 without a bearer, and the audit_logs table should
   gain a row. `make mcp-stdio` boots the stdio process; in a
   second terminal `echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python -m app.mcp --transport stdio`
   should return the tool list.

## Not included (deliberate, v1)

- **The audit-log template the user mentioned in the kickoff** (a
  generic `audit.record(event, payload, ...)` over a JSONB store
  with first-class viewer UI) is a *follow-up module* on top of this
  template, not a M0–M9 deliverable. The current audit story is the
  same `audit_logs` table UM uses, with a thin mcp wrapper.
  Promoting it to a reusable template module is the obvious next
  step after the mcp-server ships.
- **MCP without user-management** (e.g. for projects where the user
  table is owned elsewhere) — out of scope. Every line in this
  template assumes UM is present. The path to it later is a separate
  module: an `external_idp` shim that implements the same
  `resolve_viewer_from_scope` interface against an OIDC provider's
  JWKS.
- **Tools, prompts, and resources beyond the two built-in demos.**
  Project authors add their own by calling `server.tool(...)` /
  `@register_tool` from their own modules; the built-ins exist to
  prove the wiring, not to be a real catalog.

## UM is unmodified

Every file this template shares with the user-management template is
either byte-identical (the parts of `conftest.py`, `__init__.py`,
`models/entities.py`, `pyproject.toml`, etc. that don't change) or a
strict superset (`main.py`, `config.py`). The `mount_oauth_routes`
EDIT is the only place the surface of a UM function is widened, and
it is backwards-compatible by default. A UM project that does NOT
adopt MCP keeps working unchanged.
plus the identity-domain delta below, as one complete runnable app. The
`add-user-management` skill applies this manifest to a scaffold-derived
project — copying every ADD, applying every REPLACE, and checking each EDIT
trigger. Relative paths are template-root-relative (`backend/…`,
`frontend/…`).

Rule of thumb for REPLACE files: they are strict supersets of the scaffold
version — everything the scaffold had is still there, identity concerns are
added around it. When the target project has already diverged from the
scaffold, the skill must three-way compare (scaffold ↔ template ↔ target) and
replay the identity additions onto the target's version instead of
overwriting it.

## Backend — ADD

| File | Contents |
|---|---|
| `backend/app/auth/__init__.py` | Empty package marker. |
| `backend/app/auth/passwords.py` | PBKDF2-SHA256 hash/verify (200k iters), `needs_rehash`, async wrappers via `asyncio.to_thread`. |
| `backend/app/auth/tokens.py` | The single `auth_tokens` table's three token kinds (web / static / OAuth access), issue/verify/revoke with the ADR-0004 predicate discipline. `revoke_all_for_user` is the choke point that also revokes the OAuth refresh-token store. |
| `backend/app/auth/permissions.py` | The code-defined permission catalog (the authority — no permissions table); 11 codes incl. `oauth:read`/`oauth:revoke` for provider administration. |
| `backend/app/auth/dependencies.py` | `Viewer`, `get_current_user` (bearer → viewer, must-change-password 403 gate + allow-list), `require_perm()` with import-time code validation. |
| `backend/app/auth/audit.py` | `write_audit()` + secret sanitizing (redact, truncate, depth-limit). |
| `backend/app/auth/oidc.py` | OIDC client: multi-provider registry built from the nested `oidc.providers` settings block (discovery-based or explicit-endpoint providers, `subject_claim` mapping, labels), discovery cache, PKCE, HMAC state cookie with login/link modes, userinfo identification, `_open_client()` test seam. |
| `backend/app/auth/oauth21.py` | OAuth 2.1 provider: DCR, PKCE, HMAC login-blob hand-off to the SPA authorize page, atomic code claim, refresh rotation + replay detection, family revocation, AS/PRM metadata, `mount_oauth_routes()`. Exposes `revoke_grant()` (caller-session, no commit) — the per-(user × client) revocation the admin endpoint uses. |
| `backend/app/core/timeutil.py` | `utcnow()` tz-aware helper (scaffold uses inline `func.now()` defaults; identity code needs Python-side timestamps). |
| `backend/app/services/users.py` | User CRUD + role assignment, self-protections, last-admin guard, `authenticate()` with lockout. |
| `backend/app/services/roles.py` | Role CRUD, catalog-validated permission binding, system-role protection. |
| `backend/app/schemas/auth.py` | All identity request/response models (never exposes hashes). |
| `backend/app/api/auth.py` | `/api/v1/auth/*`: login/logout/me/change-password/profile (self-service contact edit), OIDC login+callback for any configured provider, self-service identity linking (`GET /identities`, link start, unlink with the last-credential 409 guard), OAuth authorize info+submit. One commit per request at the end; failed login commits audit before raising. |
| `backend/app/api/admin.py` | `/api/v1/admin/*`: permissions catalog, users CRUD + reset-password + force-logout, roles CRUD, OAuth provider administration (client listing, live grants, per-grant revoke — DCR is open, so the listing is the operator's only visibility), audit listing. Every endpoint declares `require_perm`. |
| `backend/alembic/versions/0002_user_management.py` | 10 identity tables + seed (admin role = all catalog permissions, user role, admin user with forced first-login change). The seed reads `initial_admin_password` through the layered Settings — env wins, but a value in `.env` or `app.yaml` now works too (the pre-layered version read bare `os.environ`, so `.env` was silently ignored). Chains onto `0001_scaffold_base`. |
| `backend/tests/helpers.py` | `seed_admin()`, `login()` shared by the identity suites. |
| `backend/tests/test_auth_password.py` | 9 tests: login, 401 audit, lockout, gate, change-password semantics, revocation, expiry. |
| `backend/tests/test_rbac.py` | 9 tests: catalog, role CRUD, permission effectiveness, 403 matrix, self/last-admin protections, token-kind isolation, audit listing. |
| `backend/tests/test_oidc.py` | 13 tests via `httpx.MockTransport` (zero network): provider listing with labels, redirect shape, callback provision/linking (incl. `phone_number` claim), the two endpoint shapes (discovery vs explicit URLs with an int `id` subject), state tamper, IdP failure paths. |
| `backend/tests/test_oauth21.py` | 14 tests: metadata shape (byte-exact iss), DCR, full code+PKCE flow, single-use codes, refresh rotation/replay, revocation — incl. the regressions that password change / force logout / admin reset also kill OAuth refresh tokens (no grant revival after re-password), and the admin surface: client/grant listings, per-grant revoke (kills access + refresh, idempotent, audited), permission 403 matrix. |
| `backend/tests/test_profile.py` | 6 tests: admin phone roundtrip (set/absent-unchanged/""-clears), duplicate-email 409 (admin + self paths), self profile update + field-list audit, unset-vs-clear semantics, must-change-gate whitelist. |
| `backend/tests/test_oidc_config.py` | 4 tests on the nested `oidc` settings block: enabled-requires-credentials-and-endpoints startup error, provider-key case folding + cross-source merge, reserved/invalid keys rejected, scopes as list-or-string. |
| `backend/tests/test_identity_link.py` | 17 tests on self-service linking: state-blob modes (link roundtrip, legacy login blobs, missing user id fails closed), link start (cookie pins the user, unknown provider 404, IdP down 502), callback attach (idempotent, inactive user, owned-by-other, unique-constraint race), listing with label fallback, unlink (happy, foreign 404, last-credential 409), must-change gate. |

## Backend — REPLACE (scaffold-owned files, strict supersets)

| File | What changed vs scaffold |
|---|---|
| `backend/app/models/entities.py` | Same demo `Item`; adds the 10 identity tables (users, roles, user_roles, role_permissions, oauth_identities, oauth_clients, oauth_codes, oauth_refresh_tokens, auth_tokens, audit_logs) with named constraints/indexes. `Item` timestamps gained explicit `DateTime(timezone=True)` — mirror that onto a diverged target (keeps `alembic autogenerate` quiet). |
| `backend/app/core/config.py` | Adds the identity settings block: `secret_key`/`hmac_secret`, `initial_admin_password`, token TTL, lockout, the nested `oidc` registry (`redirect_base` + `providers` map with per-provider validation), `web_base_url`, `oauth21_*`. Scaffold settings and the layered-config wiring (`settings_customise_sources` + `JinjaYamlSource`, added to the scaffold in the same phase) are untouched prefixes. |
| `backend/app/core/config_yaml.py` | Identical mirror of the scaffold's — kept byte-identical on purpose (drift check enforces); listed here only so a diverged target knows it must exist. |
| `backend/app/main.py` | Adds `RequestMetaMiddleware` (ip/user-agent capture for audit), includes the auth + admin routers, and mounts the OAuth 2.1 routes at the root when enabled. The mcp-server template later moves that mount into its sub-app. |
| `backend/pyproject.toml` | Adds `email-validator` (EmailStr) and `mcp>=2.2.0,<3` (OAuth 2.1 routes use the SDK's request/response models). (`jinja2`/`pyyaml` come from the scaffold since the layered-config phase.) |
| `backend/tests/conftest.py` | Same DB lifecycle; adds the `admin_headers` fixture (seed + login). |
| `backend/tests/__init__.py` | Adds the package docstring (pytest 9 resolves helpers as `tests.<module>`). |

## Frontend — ADD

| File | Contents |
|---|---|
| `frontend/src/api/auth.ts` | Typed wrappers for every identity endpoint (session incl. `updateProfile`, SSO providers, linked identities list/link-start/unlink, authorize, admin users/roles/permissions/OAuth clients+grants+revoke/audit). |
| `frontend/src/components/auth/AuthContext.tsx` | Session state (`loading`/`authenticated`/`anonymous`), token storage, login/logout/adoptToken/refresh, `hasPerm` for display gating. |
| `frontend/src/components/auth/RequirePerm.tsx` | Route-level permission gate rendering an explicit no-access panel. |
| `frontend/src/components/auth/AuthShell.tsx` | Centered card chrome for the standalone auth pages. |
| `frontend/src/pages/LoginPage.tsx` | Password form + SSO buttons (rendered only when `/auth/oauth/providers` lists any). |
| `frontend/src/pages/ChangePasswordPage.tsx` | Self-service change; lands here for must-change accounts (also reachable directly). |
| `frontend/src/pages/OAuthCallbackPage.tsx` | OIDC landing: parses `#token=…`/`#error=…`, scrubs the fragment, adopts the session. |
| `frontend/src/pages/OAuthAuthorizePage.tsx` | OAuth 2.1 agent consent: shows client + scopes from the signed blob, submits credentials once, navigates the returned redirect URL. |
| `frontend/src/pages/ProfilePage.tsx` | Self-service profile (`/profile`, every authenticated user): display-name/email/phone form + inline password change that adopts the re-issued token + the linked-accounts card (list, connect buttons for enabled unlinked providers, unlink behind a confirm; consumes and scrubs the `#linked=`/`#link_error=` outcome fragment). |
| `frontend/src/pages/admin/UsersPage.tsx` | Users table + create/edit dialogs, reset password, force logout, delete — every action permission-gated in the UI. |
| `frontend/src/pages/admin/RolesPage.tsx` | Roles table + editor with the permission catalog grouped by `group`; system roles protected. |
| `frontend/src/pages/admin/OAuthPage.tsx` | OAuth provider view (`/oauth`, gated by `oauth:read`): active grants (user × client × scopes × expiry) with per-grant revoke behind `oauth:revoke`, plus the registered-client listing. |
| `frontend/src/pages/admin/AuditPage.tsx` | Read-only audit trail with event/username filters and offset pagination. |

## Frontend — REPLACE (scaffold-owned files, strict supersets)

| File | What changed vs scaffold |
|---|---|
| `frontend/src/api/client.ts` | Adds token storage helpers (`cliver-token` localStorage key), default bearer source, and the response interceptors: 401 → clear + hard redirect `/login`; 403 `must_change_password` → `/change-password` (both loop-suppressed on auth pages). |
| `frontend/src/App.tsx` | Wraps routes in `AuthProvider`; adds the standalone auth routes (`/login`, `/change-password`, `/auth/callback`, `/oauth/authorize`), the ungated `/profile` route, and the permission-guarded admin routes (`/users`, `/roles`, `/oauth`, `/audit`) around the scaffold's `/` and `/items`. The admin `/oauth` page coexists with the standalone `/oauth/authorize` flow page (react-router ranks the exact match higher). |
| `frontend/src/layouts/AppLayout.tsx` | Adds the auth guard (loading placeholder, anonymous → `/login` with return path, must-change → gate), permission-gated admin nav items, and the user menu with Profile + logout (the scaffold's Home/Items entries stay ungated). |
| `frontend/src/locales/en.json` | Adds `nav.*`, `auth.*`, `admin.*`, `profile.*` keys (scaffold keys untouched). |
| `frontend/src/locales/zh.json` | Same keys, Chinese. |

## Root — REPLACE

| File | What changed vs scaffold |
|---|---|
| `app.yaml` | Same header + `app_name`/`log_level`/`database_url` blocks as the scaffold's; appends the `oidc` section: `redirect_base` plus `google` and `github` presets, both `enabled: false` with empty credentials (an enabled provider without credentials would fail startup). Deliberately does NOT set `oauth21_issuer_url`. |
| `.env.example` | Documents the identity settings block (all commented; defaults shown), including the nested OIDC override names (`CLIVER_OIDC__PROVIDERS__<KEY>__*`). |

## EDIT

None — every change folds into the REPLACE supersets. The Alembic chain needs
no edits either: `0002_user_management` hangs off `0001_scaffold_base`
(down_revision fixed). In a project whose chain has diverged, adjust
`down_revision` to the current head (or `alembic merge`) instead.

## Post-copy checklist

1. `cd backend && uv sync` — installs `email-validator` + `mcp`.
2. `uv run alembic upgrade head` — creates the identity tables and prints the
   generated admin password if `CLIVER_INITIAL_ADMIN_PASSWORD` was unset.
   A database already migrated from an OLDER copy of this template (before
   the OAuth catalog codes existed) needs the admin role granted
   `oauth:read`/`oauth:revoke` manually — fresh installs seed them from the
   catalog automatically.
3. `uv run pytest` — 87 tests (78 identity + 9 scaffold), all offline-capable
   except the DB (needs the compose PostgreSQL).
4. `cd frontend && pnpm install && pnpm build` — no new frontend dependencies.
5. Manual: log in as admin → forced password change → Users/Roles/OAuth/Audit
   pages; create a role without permissions → that account sees no admin nav
   and gets 403s server-side; open the user menu → Profile → edit contact
   details and change the password (other sessions drop); connect an agent via
   OAuth once → the grant appears on the OAuth page → revoke it → the agent's
   token dies.

## Migrating a project from the pre-layered template (breaking)

The identity settings moved to layered configuration in the layered-config
phase. Projects copied from an older template must:

- Copy `backend/app/core/config_yaml.py`, the `settings_customise_sources`
  wiring in `config.py`, and root `app.yaml` (the three together are the
  mechanism — see the scaffold's README for the precedence model).
- **Rename the flat OIDC env vars to nested ones.** The old
  `CLIVER_OIDC_ISSUER` / `CLIVER_OIDC_CLIENT_ID` / … are `extra="ignore"`:
  they are SILENTLY DROPPED, and the login page's SSO buttons disappear
  without any error. The nested spellings are
  `CLIVER_OIDC__PROVIDERS__<KEY>__ISSUER`, `…__CLIENT_ID`, `…__CLIENT_SECRET`,
  `…__SCOPES`, `…__AUTO_PROVISION`, `…__DEFAULT_ROLE`, plus
  `CLIVER_OIDC__REDIRECT_BASE` for the redirect base. (`extra="ignore"` stays
  on purpose: the test suite injects `CLIVER_TEST_DATABASE_URL` through it.)
- Re-pin `pydantic-settings>=2.16,<3` and add `jinja2`/`pyyaml` (already
  direct scaffold deps).

## Not included (deliberate)

- Email verification / password reset by email — needs an SMTP story; add per
  project when real. (Self-service profile editing of display name/email/phone
  IS included; what is missing is *verifying* the email address.)
- User avatar upload — needs a file-storage story per project.
- TOTP/WebAuthn second factor — the token/audit plumbing is ready for it.
