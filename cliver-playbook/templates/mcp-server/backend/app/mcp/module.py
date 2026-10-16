"""Module entry: what the parent ``main.py`` calls to wire the MCP server
into the FastAPI application.

Filled in by M1 (structure) + M2 (lifespan composition + subapp mount).
The current M0 stub just exposes the symbol the parent ``main.py`` will
import, so wiring it in later is a one-line change rather than a refactor.
"""

from __future__ import annotations

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """Mount the MCP sub-app on ``settings.mcp.mount_path`` and enter its
    lifespan context from the parent app's lifespan.

    No-op at M0; M1 adds the registration of default tools, M2 adds the
    sub-app mount and lifespan composition, M3 adds the auth gate
    conditional on ``settings.mcp.auth_enabled``.
    """
    # M0: intentionally a no-op so the rest of the import graph stays
    # valid and the parent main.py can already `from app.mcp import register`
    # without conditional logic.
    return
