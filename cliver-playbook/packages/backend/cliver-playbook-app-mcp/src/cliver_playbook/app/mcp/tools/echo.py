"""``echo`` — the public-tool exemplar and the identity probe.

Doubles as the connectivity check an agent calls first: it reports how
the server currently identifies the caller — authenticated user (or
null), agent headers, transport — which is exactly what is hard to see
from the client side when a permission-gated call fails.

Public on purpose (``@public_tool()``): it carries no data of its own,
so it is safe under auth OFF and for viewers with no permissions. It is
also the reference for how little a useful tool needs — a signature,
a docstring the model can read, and the decorator doing the
cross-cutting work.
"""

from __future__ import annotations

from typing import Any

from cliver_playbook.app.mcp.context import (
    AnonymousViewer,
    current_agent,
    current_request,
    current_viewer,
)
from cliver_playbook.app.mcp.server import mcp
from cliver_playbook.app.mcp.settings import settings
from cliver_playbook.app.mcp.toolkit import public_tool


@mcp.tool()
@public_tool()
async def echo(message: str = "") -> dict[str, Any]:
    """Echo the message back, plus how the server identifies the caller.

    No permission required — safe to call first to verify connectivity
    and to see which user / agent identity the server resolved.

    Args:
        message: Free-form text echoed back verbatim.
    """
    viewer = current_viewer()
    user: dict[str, Any] | None = None
    if not isinstance(viewer, AnonymousViewer) and viewer.user_id is not None:
        user = {"id": viewer.user_id, "username": viewer.username}

    agent = current_agent()
    return {
        "message": message,
        "user": user,
        "agent": {
            "type": agent.normalised_type(),
            "id": agent.truncated_id(settings.mcp.agent_id_max_length),
        },
        # The ASGI scope tag: "http" for the streamable-http transport,
        # "stdio" for the standalone stdio entry, "unknown" when the
        # function is invoked outside any request.
        "transport": current_request().get("type", "unknown"),
    }
