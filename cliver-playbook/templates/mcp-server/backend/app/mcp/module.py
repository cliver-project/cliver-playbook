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

from app.mcp.tools import register_default_tools

logger = logging.getLogger("mcp.module")


def register(app: FastAPI) -> None:
    """Attach the MCP surface to the parent app.

    ``app`` is currently unused — the parameter is the seam the parent
    already calls with; future steps (per-environment tool gating,
    custom routes) grow here without touching the call site.
    """
    register_default_tools()
    logger.debug("MCP module registered: built-in tools on the server singleton")
