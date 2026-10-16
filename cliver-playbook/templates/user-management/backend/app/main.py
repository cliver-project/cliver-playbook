"""FastAPI application assembly.

Routers are included explicitly — assembly stays visible in one place. This
file is the user-management superset of the scaffold's main.py: it adds the
auth and admin routers. (The mcp-server template supersets this file with the
MCP sub-app mount; the OAuth mount below is kept as-is there — the MCP
surface reuses this provider rather than owning a copy.)

Unit of work: identity routers commit once per request at the end (service
mutations + audit row together); the scaffold's items service commits itself.
Both patterns coexist fine — each request touches one style.
"""

import logging

from fastapi import FastAPI

from app.api import admin, auth, items, meta
from app.auth.oauth21 import RequestMetaMiddleware, mount_oauth_routes
from app.core.config import settings

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("cliver_app")

app = FastAPI(title=settings.app_name, version="0.1.0")

app.include_router(meta.router)
app.include_router(items.router)
app.include_router(auth.router)
app.include_router(admin.router)

# OAuth 2.1 provider surface (agent/API clients). Routes land at the app root
# because well-known discovery must not carry a prefix. When the mcp-server
# template takes over, it REMOVES this direct mount and owns the routes in its
# sub-app instead (double mounting would shadow the gate).
app.add_middleware(RequestMetaMiddleware)
if settings.oauth21_enabled:
    mount_oauth_routes(app)

logger.info("Application assembled: %s (API prefix %s)", settings.app_name, settings.api_v1_prefix)
