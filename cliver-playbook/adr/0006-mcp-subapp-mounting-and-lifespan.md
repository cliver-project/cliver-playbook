> **Superseded by ADR-0017** (2026-10-16): the MCP protocol endpoint is now an
> ordinary route inside the package's `APIRouter`, composed with every other
> package's routers through `include_router` — no `Mount`, and no hand-composed
> sub-app lifespan, because the session manager is entered from the
> application's own lifespan. The transport settings decided here
> (`stateless_http=True`, DNS-rebinding protection off, one build per process)
> were carried over unchanged. Kept for history.

# ADR-0006: MCP sub-app mounting and lifespan composition

**Status:** Accepted (2026-10-16)
**Context:** `templates/mcp-server` — how the MCP server attaches to the FastAPI app, and
why one OAuth 2.1 provider serves both the Web and the agents.

## Decision

1. **Same process by default.** The official SDK's `streamable_http_app()` builds a
   Starlette app; the parent FastAPI app mounts it at `/` **after** including every
   `/api/v1` router (Starlette matches in order, so API paths win first and the sub-app
   answers the rest). The SDK's route inside the sub-app sits at
   `settings.mcp.mount_path` (default `/mcp`) as an **exact-match path**. A
   `Mount("/mcp", …)` + child `Route("/")` composition was measured to answer
   `POST /mcp` with a 307 redirect to `/mcp/` — clients POST the URL they were given,
   so the exact-match layout avoids depending on redirect-following.

2. **Lifespan composition is the seam.** A mounted sub-app's lifespan does NOT run
   automatically. The parent's `lifespan` enters
   `subapp.router.lifespan_context(subapp)` explicitly — that context boots/shuts the
   SDK's streamable-http session manager. Verified against mcp 2.3.0 (2026-10-16 spike);
   locked down by `tests/test_mcp_subapp.py` and the real-port tests so an SDK bump
   fails in CI.

3. **One build per process, memoized.** `build_mcp_subapp()` caches its instance: the
   SDK registers the session manager on the server singleton as a build side-effect, so
   a second build would orphan the first app's manager.

4. **`stateless_http=True`.** Every POST is self-contained (no sticky session id in
   headers). Simpler for proxies and for the audit story: one POST = one tool call =
   one audit row.

5. **DNS-rebinding protection explicitly off.** The SDK auto-enables it with a
   localhost-only allowlist when transport-security settings are omitted and the bind
   host is local — which would 403 any LAN client the moment the server is reached from
   another machine. The parent FastAPI app performs no host filtering either, so the
   consistent template default is off; public deployments should sit behind a reverse
   proxy that validates `Host`. Content-Type is still enforced on POSTs by the
   transport itself.

6. **The auth gate is wrapped in place, always present.** `build_mcp_subapp()` replaces
   the SDK route's ASGI app with `MCPGateMiddleware(route.app)` — the route keeps its
   exact path and the sub-app keeps its lifespan. The gate reads
   `settings.mcp.auth_enabled` **per request**, so the ON/OFF switch never rebuilds the
   app and the build can never accidentally ship without the gate (see ADR-0014).

7. **Standalone process is supported, not the default.** `python -m app.mcp --transport
   stdio|http` starts a separate process. `stdio` serves the MCPServer over
   stdin/stdout (the standard MCP stdio transport — the agent spawns and speaks to it).
   `http` serves the **full parent app** (API + MCP + OAuth) with uvicorn on its own
   port, not just the sub-app: the OAuth authorize flow needs the API routes and
   redirects to the Web frontend's login page, so an MCP-only listener would advertise
   a protected-resource metadata document whose flow dead-ends.

8. **One OAuth 2.1 provider, mounted at the root, for both surfaces.** The MCP template
   does NOT mount an MCP-scoped copy of the OAuth routes and adds **no `mount_path`
   parameter** to `mount_oauth_routes()`. Reasons: the provider's protected-resource
   metadata already declares `resource = {base}/mcp` (that value predates this
   template), the gate's 401 `WWW-Authenticate` header points agents at the root PRM,
   and a single provider keeps DCR registrations, grants and revocation state
   single-sourced — one Web action (`oauth:revoke`, force-logout) revokes an agent.
   Mount order is safe even though `mount_oauth_routes(app)` is called after the `/`
   mount: it prepends to `app.router.routes` (`[:0]`), so the OAuth and well-known
   routes always match before the sub-app's catch-all. (An earlier design sketch—a
   second copy under `/mcp/oauth`—was dropped for exactly this duplication.)

## Consequences

- `mcp.mount_path` is validated (starts with `/`, no trailing `/`) because it becomes
  the SDK route's exact path. Changing it also means moving the Vite dev proxy entry
  (`/mcp`) with it.
- The `/` mount is a catch-all: parent routes added AFTER it in registration order
  would be shadowed. The assembly order in `main.py` is therefore load-bearing —
  routers first, then `app.mount("/", subapp)`, then the root OAuth mount (which
  prepends). New parent routes go through `include_router` before the mount.
- The sub-app's route layout is SDK-internal: the in-place gate wrap raises loudly
  (`RuntimeError`) if the SDK stops exposing a route at `mount_path`, so an upgrade
  breaks at boot, not silently.
- Under `--transport http` the same app is served twice if the Web process also runs —
  a deliberate deployment shape (systemd unit / sidecar on a distinct port) sharing one
  database; docs say so in `transport.py` and the Makefile.

## Alternatives considered

- **`Mount("/mcp", subapp)` with a prefix-stripping child route** — measured 307
  redirect on the exact URL clients are given; rejected.
- **Sidecar process only** — more moving parts for zero benefit in local dev; the
  standalone entry is kept as an option (`make mcp-stdio` / `make mcp-http`), not the
  default deployment.
- **An SDK middleware hook for the gate** — mcp 2.x exposes none; wrapping the route's
  ASGI app in place is the minimal supported surface (upstream feature request noted,
  not blocking).
- **Lifespan via `mcp.session_manager.run()` directly** — SDK-private surface with more
  upgrade risk than the public `router.lifespan_context` seam; rejected.
