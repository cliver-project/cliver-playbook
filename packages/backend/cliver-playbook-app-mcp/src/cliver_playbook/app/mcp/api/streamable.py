"""The MCP protocol endpoint — an ordinary route in an ``APIRouter`` (ADR-0017).

The SDK's ``streamable_http_app()`` builds a whole Starlette application, but
all this package needs from it is one ASGI endpoint and one session manager.
Placing that endpoint as a plain :class:`starlette.routing.Route` inside a
router means the composed application reaches it the same way it reaches every
other route — one ``app.include_router(...)`` loop, no ``app.mount("/")``, no
catch-all that has to stay last, and no hidden sub-application in the route
table:

- FastAPI's ``include_router`` copies plain Starlette routes out of an
  ``APIRouter`` (rebuilding them from ``route.endpoint``), so an APIRouter is a
  valid carrier for this route. The gate must therefore be part of the endpoint
  object itself — a post-construction ``route.app = ...`` rewrite would be
  discarded by that copy (spike 2026-10-16, fastapi 0.143).
- The path is exact-match ``/mcp`` — no trailing-slash redirect, because
  clients POST the URL they were given, and the OAuth 2.1 provider's
  protected-resource metadata publishes exactly ``{base}/mcp`` as the resource
  identifier (see the note on ``MCP_PATH`` below).
- ``methods=None`` on the route: the transport answers POST (JSON-RPC),
  GET (server-push stream, 405 with a JSON-RPC error body in stateless mode)
  and DELETE itself, so method handling stays SDK policy.

Lifecycle: the SDK's session manager must be running before the first request,
and may be started once per instance. :func:`install_streamable_app` creates it
(memoized, one per process) and the application lifespan enters
:func:`session_manager`'s ``run()`` — the same context the SDK's own Starlette
lifespan enters, entered from ours instead (spike 2026-10-16, mcp 2.3.0).

Import purity: building the route at import costs nothing and touches no SDK
state; the session manager is created by :func:`install_streamable_app`, which
only the lifespan calls. A request that arrives before the lifespan ran fails
loudly with a RuntimeError naming the wiring step that was skipped (ADR-0016).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.routing import Route

from cliver_playbook.app.mcp.auth import MCPGateMiddleware
from cliver_playbook.app.mcp.server import mcp
from cliver_playbook.app.mcp.tools import register_default_tools
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)
from mcp.server.transport_security import TransportSecuritySettings

# The protocol endpoint path. Fixed on purpose — see the settings module
# docstring: the OAuth 2.1 protected-resource metadata names `{base}/mcp` as
# the resource identifier, so a configurable path could disagree with the
# metadata agents discover. A project that vendors this package and wants a
# different path edits this constant (and its reverse proxy) in one place.
MCP_PATH = "/mcp"

router = APIRouter(tags=["mcp"])

# Process-wide flag for the one-shot install below. The SDK registers the
# session manager on the server singleton as a side effect of building the
# app, so a second build would orphan the first manager (and its ``run()``
# could never be entered twice).
_installed = False


class _StreamableEndpoint:
    """ASGI endpoint that resolves the session manager per request.

    Deliberately a class instance, not a function: Starlette treats a
    callable object as raw ASGI (a function would be wrapped in
    ``request_response`` and never see the transport's own request handling).
    Resolution is deferred to call time so importing this module does not
    build SDK state.
    """

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await StreamableHTTPASGIApp(session_manager())(scope, receive, send)


def install_streamable_app() -> StreamableHTTPSessionManager:
    """Create the SDK app + session manager once per process; return the manager.

    Called by the application lifespan (``app.create_app``'s) before serving —
    never at import. Idempotent: repeated calls return the same manager, and
    the SDK app is built at most once.

    Also registers the built-in tools: anything that turns this endpoint on
    should serve the same tool set, and doing it here means a composed
    application cannot end up with a reachable endpoint and an empty tool
    list.
    """
    global _installed
    if not _installed:
        # Register the built-ins before the endpoint can serve anything: the
        # stdio entry does the same on its own path, so both transports expose
        # one tool set (see tools/__init__.py).
        register_default_tools()
        # stateless_http=True: every POST is self-contained (no sticky session
        # id in headers). Simpler for proxies and for the audit story — one
        # POST = one tool call = one audit row — and it matches the deployment
        # shape remote agents actually use.
        #
        # DNS-rebinding protection explicitly off: the SDK auto-enables it with
        # a localhost-only allowlist when transport security is omitted and the
        # bind host is local, which would 403 any LAN client the moment the
        # server is reached from another machine. The parent FastAPI app
        # performs no host filtering either, so the consistent default is off;
        # public deployments should sit behind a reverse proxy that validates
        # Host. Content-Type is still enforced on POSTs by the transport.
        mcp.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        _installed = True
    return mcp.session_manager


def session_manager() -> StreamableHTTPSessionManager:
    """The installed session manager, or a loud error naming the missing step.

    The manager exists only after :func:`install_streamable_app` ran, which
    ``create_app``'s lifespan does. Reaching this without it means the
    application was assembled by hand without the MCP lifespan — a wiring bug
    that must not degrade into an unexplained 500.
    """
    try:
        return mcp.session_manager
    except RuntimeError as exc:  # pragma: no cover — wiring bug, not a code path
        raise RuntimeError(
            "The MCP session manager is not installed: build the application through "
            "cliver_playbook.app.mcp.create_app (which installs it in its lifespan), or "
            "call install_streamable_app() and enter session_manager().run() from your "
            "own lifespan before serving requests."
        ) from exc


# The gate is part of the endpoint passed into the route: FastAPI's router
# inclusion rebuilds plain Starlette routes from `route.endpoint`, so wrapping
# the route's app afterwards would silently drop the gate. The gate reads
# settings.mcp.auth_enabled per request, so the ON/OFF switch never rebuilds
# anything and no build can ship without the gate (ADR-0014).
router.routes.append(Route(MCP_PATH, endpoint=MCPGateMiddleware(_StreamableEndpoint())))
