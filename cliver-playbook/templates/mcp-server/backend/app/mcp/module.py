"""Module entry: what the parent ``main.py`` calls to wire the MCP server
into the FastAPI application.

The ``mcp:*`` permission codes are part of the shared catalog via a
static edit to ``app/auth/permissions.py`` (see INTEGRATION.md) — nothing
to register at runtime.

Tool registration lives behind this seam so every process that
assembles the app (uvicorn, tests, the standalone entry in M6) exposes
the same tool set. The sub-app mount itself stays in ``main.py``: its
lifespan must compose with the parent's, which only the assembly site
can arrange.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.mcp import api
from app.mcp.tools import register_default_tools

logger = logging.getLogger("mcp.module")


def register(app: FastAPI) -> None:
    """Attach the MCP surface to the parent app.

    The parent calls this BEFORE its ``/`` mount of the MCP sub-app
    (Starlette matches in order), so routes included here win over the
    sub-app's catch-all and are reachable as ordinary API endpoints.
    """
    app.include_router(api.router)
    register_default_tools()
    logger.debug("MCP module registered: discovery route + built-in tools on the server singleton")
