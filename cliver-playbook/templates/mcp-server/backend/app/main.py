"""FastAPI application assembly.

Routers are included explicitly — assembly stays visible in one place. This
file is the mcp-server superset of the user-management template's main.py: in
addition to UM's auth and admin routers, it mounts the MCP server's
sub-application at ``settings.mcp.mount_path`` (default ``/mcp``) and drives
its lifespan from the parent's. The MCP subapp owns the OAuth 2.1 routes
under its prefix, so the Web's root-level OAuth mount is suppressed here.

Unit of work: identity routers commit once per request at the end (service
mutations + audit row together); the scaffold's items service commits itself.
Both patterns coexist fine — each request touches one style.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, auth, items, meta
from app.auth.oauth21 import RequestMetaMiddleware, mount_oauth_routes
from app.core.config import settings

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("cliver_app")


# Lifespan: combine the MCP subapp's session-manager startup/shutdown with
# the parent FastAPI's. The MCP SDK exposes this as ``subapp.router.lifespan_context``
# — entered by the parent's lifespan, the subapp's state machines boot and
# shut down with the parent. Verified against mcp 2.3.0 (spike 2026-10-16).
# The subapp is built once at module level below (single build: the SDK
# registers its session manager on the server singleton as a side-effect,
# so a second build would orphan the first one's manager); the lifespan
# closes over that same object.
from app.mcp import register as mcp_register
from app.mcp.subapp import build_mcp_subapp

_mcp_subapp = build_mcp_subapp()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _mcp_subapp is not None:
        async with _mcp_subapp.router.lifespan_context(_mcp_subapp):
            yield
    else:
        yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.include_router(meta.router)
app.include_router(items.router)
app.include_router(auth.router)
app.include_router(admin.router)

# MCP module seam: catalog is extended statically (see app/mcp/permissions.py);
# later steps hang default-tool registration off this call.
mcp_register(app)

# MCP sub-application mounted at "/" AFTER the API routers: Starlette
# matches in order, so every /api/v1/* route wins first and the sub-app
# answers the rest. The SDK route inside it sits at settings.mcp.mount_path
# (default /mcp) — exact-match, no trailing-slash redirect.
if _mcp_subapp is not None:
    app.mount("/", _mcp_subapp)
    logger.info("MCP endpoint mounted at %s", settings.mcp.mount_path)

# OAuth 2.1 provider surface stays at the root exactly as in user-management:
# routes are added BEFORE the "/" mount below, so they win over the sub-app
# and the Web's DCR/authorize flows are byte-identical to the UM template.
# (A future step may mount an MCP-scoped copy under settings.mcp.mount_path
# + /oauth via a mount_path parameter on mount_oauth_routes, for agents that
# discover the AS from the MCP WWW-Authenticate header; that addition will
# not remove this root mount.)
app.add_middleware(RequestMetaMiddleware)
if settings.oauth21_enabled:
    mount_oauth_routes(app)

logger.info("Application assembled: %s (API prefix %s)", settings.app_name, settings.api_v1_prefix)
