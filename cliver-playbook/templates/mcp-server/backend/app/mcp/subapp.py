"""Build the MCP sub-application for mounting on the parent FastAPI.

M0 stub: returns ``None`` so the parent's mount call is a no-op and the
import graph stays valid. M2 will fill this in with
``streamable_http_app(stateless_http=True)`` from the official mcp SDK,
wrapped in the auth gate when ``settings.mcp.auth_enabled`` is true.

The function lives in its own module (not inline in ``module.py``) so
``main.py`` can import it without pulling in the SDK at import time
during the M0 baseline — this keeps the existing UM test suite (which
never sets ``CLIVER_MCP__*`` settings) green as the new template's
copies of UM code start running.
"""

from __future__ import annotations

from typing import Any


def build_mcp_subapp() -> Any:
    """Return a Starlette ASGI app to be mounted at ``settings.mcp.mount_path``.

    Returns ``None`` until M2 lands; the parent ``main.py`` checks for
    ``None`` and skips the mount in that case, so this function's return
    value drives the assembly.
    """
    return None
