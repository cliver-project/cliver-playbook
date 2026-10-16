"""Module entry: what the parent ``main.py`` calls to wire the MCP server
into the FastAPI application.

The ``mcp:*`` permission codes are part of the shared catalog via a
static edit to ``app/auth/permissions.py`` (see INTEGRATION.md) — nothing
to register at runtime. This seam exists so the parent ``main.py`` has a
single call that future steps can grow into (M2: sub-app mount helpers,
M4: default tool registration).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

logger = logging.getLogger("mcp.module")


def register(app: FastAPI) -> None:
    """Attach the MCP surface to the parent app. No-op at M1.

    Kept as an explicit seam: the parent main.py calls this once at
    assembly time. Later steps add the default tool registration here
    (the sub-app mount itself stays in main.py so the lifespan context
    composes with the parent's, not per-module).
    """
    logger.debug("MCP module registered (no-op at M1)")
    # M4 will add: from app.mcp.tools import register_default_tools
    #               register_default_tools()
