"""Build the MCP sub-application — an SDK Starlette app owned by this module.

The sub-application is the official SDK's ``streamable_http_app()`` built
from the :data:`app.mcp.server.mcp` singleton with:

- ``streamable_http_path=settings.mcp.mount_path`` — the SDK's internal
  route lands at exactly ``/mcp`` (no trailing slash). The parent app
  mounts the whole sub-app at ``/`` *after* including the API routers,
  so API paths match first and the MCP endpoint gets the rest. A
  ``Mount("/mcp", ...)`` + child ``Route("/")`` composition was measured
  to answer ``POST /mcp`` with a 307 redirect to ``/mcp/`` — clients
  POST the URL they were given, so the exact-match layout here avoids
  depending on redirect-following.

- ``stateless_http=True`` — every POST is self-contained (no sticky
  session id in headers). Simpler for proxies and for the audit story:
  one POST = one tool call = one audit row. Matches the deployment
  shape remote agents (browser-assistant style) actually use.

- DNS rebinding protection explicitly **off**. The SDK auto-enables it
  with a localhost-only allowlist when transport security settings are
  omitted and the bind host is local — which would 403 any LAN client
  (``Host: 192.168.x.x``) the moment the server is reached from another
  machine. The parent FastAPI app performs no host filtering either, so
  the consistent template default is off; public deployments should sit
  behind a reverse proxy that validates Host, and Content-Type is still
  enforced on POSTs by the transport itself.

Built exactly once per process (idempotent): the SDK registers the
session manager on the server singleton as a side-effect, so a second
build would orphan the first app's manager. ``main.py`` builds it at
module import, mounts it, and re-enters it via
``subapp.router.lifespan_context(subapp)`` inside the parent lifespan —
that context is what boots/shuts the streamable-http session manager
(spike-verified against mcp 2.3.0). The standalone entry (M6) serves
the same object with uvicorn directly, whose own lifespan handling
runs the same context.
"""

from __future__ import annotations

from typing import cast

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app.core.config import settings
from app.mcp.server import mcp

# Process-wide single instance. ``None`` until the first build; the parent
# treats a ``None`` return as "MCP surface absent" (kept from the M0 stub
# contract so assembly code never needs to change shape).
_subapp: Starlette | None = None


def build_mcp_subapp() -> Starlette | None:
    """Return the MCP sub-application, building it on first call.

    Subsequent calls return the same instance — see the module docstring
    for why a second build would be a bug (orphaned session manager).
    """
    global _subapp
    if _subapp is not None:
        return _subapp

    _subapp = cast(
        Starlette,
        mcp.streamable_http_app(
            streamable_http_path=settings.mcp.mount_path,
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        ),
    )

    # Wrap the SDK route's ASGI app with the auth gate, in place: the route
    # keeps its exact path and the sub-app keeps its lifespan (the session
    # manager still boots exactly once via the parent's lifespan). The gate
    # is ALWAYS in the chain — it reads settings.mcp.auth_enabled per
    # request, so the ON/OFF switch never requires rebuilding the app (and
    # the build can never accidentally ship without the gate).
    from starlette.routing import Route

    from app.mcp.auth import MCPGateMiddleware

    for route in _subapp.router.routes:
        if isinstance(route, Route) and route.path == settings.mcp.mount_path:
            route.app = MCPGateMiddleware(route.app)
            break
    else:  # pragma: no cover — SDK layout change would break this loudly
        raise RuntimeError(
            f"SDK route for {settings.mcp.mount_path!r} not found in the "
            "streamable-http app — mcp package layout changed?"
        )
    return _subapp
