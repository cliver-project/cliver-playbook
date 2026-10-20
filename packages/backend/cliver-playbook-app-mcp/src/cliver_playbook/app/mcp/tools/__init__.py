"""MCP tool collection.

Tools self-register on the shared server singleton at import time (the
``@mcp.tool()`` decorator runs when the module is imported).
:func:`register_default_tools` imports the built-ins exactly once; every entry
point that serves MCP calls it — the application via the endpoint installer
(``api/streamable.py``), the standalone transport entry directly — so all entry
points expose the same tool set.

Adding a tool: drop a module in this package, decorate the function
with ``@mcp.tool()`` plus exactly one of ``@public_tool()`` /
``@require_perm(...)`` from :mod:`cliver_playbook.app.mcp.toolkit` (the decorator writes
the audit row — a bare ``@mcp.tool()`` function would be invisible in
the audit trail), then add its import below.
"""

from __future__ import annotations

_registered = False


def register_default_tools() -> None:
    """Import the built-in tool modules, registering them (idempotent).

    Idempotence matters because the parent app assembles once per
    process but tests import entry points in arbitrary order; the SDK
    raises on duplicate tool names, so a second call must be a no-op.
    The module system already caches the imports — the flag makes the
    guarantee explicit rather than incidental.
    """
    global _registered
    if _registered:
        return
    _registered = True
    # Import for the side effect: the decorators register on the singleton.
    from cliver_playbook.app.mcp.tools import (
        echo,  # noqa: F401
        user_directory,  # noqa: F401
    )
