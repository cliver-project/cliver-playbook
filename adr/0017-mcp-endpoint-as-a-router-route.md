# ADR-0017: The MCP endpoint is an ordinary router route

**Status:** Accepted (2026-10-16). Supersedes ADR-0006.
**Context:** The MCP package used to assemble a whole Starlette sub-application
(`streamable_http_app()`) and mount it on the parent app (`app.mount("/", …)`),
composing the two lifespans by hand. That made the MCP surface the one part of
the application that was *not* in the route table: mount order decided who won
a path collision, a mount had to stay last, and mounted sub-app lifespans do
not run on their own — the highest-risk seam in the template. The package
refactor (ADR-0015) promised one composition mechanism for every package, and
`include_router` was already it.

## Decision

1. **The protocol endpoint is a plain route in the package's `APIRouter`.** The
   SDK still builds its app (that is how the session manager is created), but
   only two things are taken from it: the ASGI endpoint and the session
   manager. `api/streamable.py` appends a
   `starlette.routing.Route(MCP_PATH, endpoint=MCPGateMiddleware(_StreamableEndpoint()))`
   to the same `ROUTERS` list every other route travels in, so assembly stays
   one `include_router` loop and the route table shows every route (ADR-0015).
   No `Mount` anywhere; the composition guard
   (`tests/test_mcp_composition.py`) asserts that, and that no two packages
   claim the same `(path, methods)` pair.
2. **The gate must be inside the endpoint object.** FastAPI's router inclusion
   rebuilds plain Starlette routes *from* `route.endpoint` (measured against
   fastapi 0.143), so a post-construction `route.app = …` rewrite — the
   obvious way to wrap a route — is silently discarded, gate and all. The
   endpoint is therefore `MCPGateMiddleware(_StreamableEndpoint())`, and the
   gate reads `settings.mcp.auth_enabled` per request: the on/off switch never
   rebuilds anything, and no build can exist without the gate (ADR-0014).
3. **The path is a constant, not a setting.** `MCP_PATH = "/mcp"`, exact-match:
   a trailing-slash variant would answer a client's POST with a 307, and the
   OAuth 2.1 protected-resource metadata publishes exactly `{base}/mcp` as the
   resource identifier, so a configurable path could silently disagree with
   what agents discover. Vendoring projects that need another path edit the
   constant and their reverse proxy in one place.
4. **The route restricts no methods** (`methods=None`). The transport answers
   POST (JSON-RPC), GET (server-push stream) and DELETE itself; declaring
   concrete methods would turn the SDK's own answers into 405s. Because it is a
   plain Starlette route, it is also absent from the OpenAPI schema, which is
   the correct outcome: JSON-RPC has no REST contract to publish.
5. **The session manager is process state, entered from our own lifespan.**
   `install_streamable_app()` builds the SDK app at most once per process
   (memoized — the SDK registers the manager on the server singleton as a build
   side-effect, so a second build would orphan the first), registers the
   built-in tools, and returns the manager; the application lifespan enters
   `run()` for the application's lifetime. `run()` may be entered once per
   instance, so there is **one running application per process** by
   construction; test suites that boot the app via `TestClient` share one
   booted client per process (module-scoped). The standalone stdio entry builds
   no ASGI app at all and binds the process runtime itself
   (`app.configure_runtime()`, ADR-0016).
6. **Permission codes register into the live catalog.** The identity package
   exposes `register_permission_codes()`; `mcp/permissions.py` registers the
   four `mcp:*` codes when the package is imported (`mcp/__init__.py` imports
   it first, and Python runs a parent package's `__init__` before any of its
   submodules, so no import path reaches a `require_perm()` call site first).
   The identity migration seeds the admin role from the *live* catalog, so a
   composed install grants the MCP codes on a fresh database and a
   user-only install has no trace of them — without editing the catalog literal
   or re-running a migration.

## Why

- One composition mechanism for every package: a path collision becomes a test
  failure instead of a mount-order accident, and there is no "last mount wins"
  rule to remember.
- Removing the sub-app removes the sub-app lifespan seam entirely — the MCP
  lifespan is now the application's own, so there is nothing to compose.
- The endpoint keeps the SDK's behaviour where it matters (`stateless_http`,
  Content-Type enforcement, transport security) while the surrounding
  application stays ordinary FastAPI.

## Carried over from ADR-0006 (still in force)

`stateless_http=True` (one POST = one call = one audit row); DNS-rebinding
protection explicitly off with a note that public deployments belong behind a
reverse proxy that validates `Host`; one build per process, memoized; one
OAuth 2.1 provider serving both the web session and agent clients.

## Non-goals

- Re-implementing the transport: the SDK's ASGI endpoint is used as-is.
- Publishing the protocol endpoint in OpenAPI, or adding a REST facade for it.

## Risks

- The route-copy semantics above are FastAPI-internal behaviour; the dependency
  is pinned at `fastapi>=0.143` and the composition guard (no mounts, unique
  routes, `/mcp` present as a method-unrestricted plain route, absent from the
  schema) fails loudly if a future version changes it.
