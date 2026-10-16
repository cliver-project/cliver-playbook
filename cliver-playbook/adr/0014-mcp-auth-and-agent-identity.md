# ADR-0014: MCP auth ON/OFF, agent identity, and the shared token table

**Status:** Accepted (2026-10-16)
**Context:** `templates/mcp-server` — who may call the MCP surface, how a calling agent
is identified, and what lands in the audit trail.

## Decision

1. **Explicit auth flag, default OFF.** `mcp.auth_enabled` (env
   `CLIVER_MCP__AUTH_ENABLED`, yaml `mcp.auth_enabled`) selects the gate's mode per
   request. OFF is a first-class mode, not an insecure accident: the gate binds an
   `AnonymousViewer` whose `has()` is always false, so `@require_perm` tools are denied
   while `@public_tool` tools answer. **Authentication and permission are orthogonal**:
   the flag controls whether a credential is required, never what a caller is granted —
   "auth off" must never silently grant permissions.

2. **No `mcp_tokens` table.** Tokens are verified through user-management's
   kind-agnostic `verify_bearer` against the shared `auth_tokens` table — Web session
   tokens, static labeled tokens and OAuth access tokens all resolve the same way and
   die through the same revocation paths. Force-logout, password change, admin reset
   and OAuth grant revocation therefore kill an agent's access with **zero new code**,
   which is the point of sharing the table. The gate denies `must_change_password`
   users (HTTP 403; the stdio bootstrap refuses to start).

3. **Identity resolution produces UM's `Viewer`** — roles and permissions loaded fresh
   per call, so a mid-session RBAC change applies to the next tool call. MCP permission
   codes (`mcp:tools:invoke`, `mcp:prompts:get`, `mcp:resources:read`,
   `mcp:agents:read`) live in the same code-defined catalog as everything else; there is
   no parallel permission system, and `@require_perm` on an MCP tool is the same
   concept as `require_perm` on a FastAPI route.

4. **Agent identity rides alongside authentication.** Every request may carry
   `X-MCP-Agent-Type` / `X-MCP-Agent-Id` headers (stdio: `MCP_AGENT_TYPE` /
   `MCP_AGENT_ID` env vars). The type is normalised at bind time — lower-cased,
   truncated, and mapped to `"unknown"` when outside `mcp.agent_type_whitelist` — so the
   audit row never carries attacker-controlled strings beyond the configured list. The
   id is truncated to `mcp.agent_id_max_length`. Both fields are recorded on **every**
   audit row, including rejections: anonymous probes still leave a trail of *which
   machine* tried.

5. **Audit goes to the existing `audit_logs` table** via UM's `write_audit`. The MCP
   delta is the event name (`mcp.tools.call` / `mcp.prompts.get` /
   `mcp.resources.read` / `mcp.auth.reject`) plus the agent fields inside the existing
   `detail` JSONB. Deliberately **no `ALTER TABLE`**: migration `0003_mcp_server` is a
   structural no-op chain anchor. Audit writes are best-effort — a failed write is
   logged and swallowed so a transient DB hiccup cannot fail an otherwise successful
   tool call.

6. **Rejection vocabulary.** 401 with an RFC 9728 `WWW-Authenticate` header
   (`resource_metadata="…/.well-known/oauth-protected-resource"`, plus the `error`
   code) for missing/invalid tokens; 403 for `must_change_password`. The body uses
   `{error, error_description}` — the OAuth error shape — rather than FastAPI's
   `detail`, because the consumers are OAuth-aware agents.

7. **stdio auth is fail-fast.** A single long-lived session has no mid-stream 401, so
   with auth ON the process refuses to start when `MCP_BEARER_TOKEN` is missing,
   invalid or `must_change_password`. Those env vars are read from the **process
   environment** (the channel an agent hands to a child process), not from `.env`.

## Consequences

- Docs, comments and UI copy must not describe auth OFF as "insecure mode" but as "no
  identity": permission-gated tools still deny. The playground page shows exactly this
  warning (en/zh).
- The Web UI's own test console declares agent type `web-playground`, so its calls are
  never mistaken for an unidentified client.
- The gate must bind agent headers **before** any rejection path — implemented in
  `MCPGateMiddleware._reject` via the audit wrapper; a test covers the
  agent-fields-on-rejection row.
- Static tokens never expire by design (ops revoke them); OAuth access tokens respect
  the Web's TTLs. Agents should prefer OAuth for long-lived access.
- `mcp:agents:read` (view the agents page / MCP-scoped audit listing) is deliberately
  distinct from `audit:read` (the full audit trail): operators can grant MCP
  observability without granting whole-system logs.

## Alternatives considered

- **A separate `mcp_tokens` table** (the ai-gov lineage): rejected — duplicates
  issuance/revocation, forces cross-table revocation logic into every admin action,
  and creates a second identity surface to audit. Sharing `auth_tokens` turns "revoke
  an agent" into an action that already exists in the Web UI.
- **Default auth ON**: rejected — local development and trusted sidecars would pay
  token ceremony for no threat-model gain; OFF + fail-closed anonymous viewer keeps
  anything permission-gated safe, and the README/docs tell operators to turn it ON
  before exposing `/mcp` beyond loopback.
- **Anonymous ⇒ admin when auth is off** (a common shortcut): rejected outright — it
  turns a dev convenience into a silent privilege grant.
- **Agent identity as a query parameter**: rejected — it leaks into URLs and logs, and
  the MCP SDK's transports carry arbitrary headers natively.
- **`ALTER TABLE audit_logs` with agent columns**: rejected — the `detail` JSONB
  already carries per-event payloads; a schema change buys indexed filtering v1 does
  not need and would fork the audit table between templates.
