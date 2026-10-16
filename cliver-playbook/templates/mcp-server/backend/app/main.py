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
@asynccontextmanager
async def lifespan(app: FastAPI):
    # The MCP subapp is built once at module import (so its routes and
    # streamable-http app are stable across requests). The lifespan
    # context below simply drives its internal session manager.
    from app.mcp.subapp import build_mcp_subapp  # late import: avoid circular

    subapp = build_mcp_subapp()
    if subapp is not None:
        async with subapp.router.lifespan_context(subapp):
            yield
    else:
        yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.include_router(meta.router)
app.include_router(items.router)
app.include_router(auth.router)
app.include_router(admin.router)

# MCP module: register the permission catalog (idempotent side-effect)
# and (at M2+) mount the streamable_http sub-application.
from app.mcp import register as mcp_register

mcp_register(app)

# MCP sub-application: the official mcp SDK's streamable_http_app, wrapped
# in a thin ASGI gate when auth is on. Mounted at settings.mcp.mount_path
# (default /mcp) so the URL space is the same as if the user composed the
# MCP server into a future modular design.
from app.mcp.subapp import build_mcp_subapp

_mcp_subapp = build_mcp_subapp()
if _mcp_subapp is not None:
    app.mount(settings.mcp.mount_path, _mcp_subapp)
    logger.info("MCP sub-app mounted at %s", settings.mcp.mount_path)

# OAuth 2.1 provider surface: when the MCP subapp is mounted, the MCP module
# owns the OAuth routes (mounted at settings.mcp.mount_path + /oauth and
# /mcp/.well-known/...). The Web's root-level mount would shadow them, so it
# is gated on the MCP module NOT being present. With the MCP subapp
# always-mounted in this template, the root mount is suppressed.
app.add_middleware(RequestMetaMiddleware)
if settings.oauth21_enabled and _mcp_subapp is None:
    mount_oauth_routes(app)

logger.info("Application assembled: %s (API prefix %s)", settings.app_name, settings.api_v1_prefix)
