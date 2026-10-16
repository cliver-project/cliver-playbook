"""MCP server (streamable-http + stdio) — consumer of user-management infrastructure.

The MCP server is the entry point for AI agents (WorkBuddy, Codex, Claude
Code, custom clients). It runs in the same process as the Web backend by
default (a lifespan-composed Starlette sub-app mounted at
``settings.mcp.mount_path``, default ``/mcp``); stdio transport is also
supported as a separate process started by ``make mcp-stdio``.

What this module owns
---------------------

- The ``MCPServer`` instance (``server.py``) and the registration
  helpers for tools, prompts, and resources.
- The transport plumbing (``transport.py`` + ``standalone.py``) for
  both streamable-http and stdio.
- The auth gate (``auth.py``) — only mounted when ``settings.mcp.auth_enabled``
  is true. ON: every request must carry a bearer from the user-management
  ``auth_tokens`` table; the gate reuses UM's ``verify_bearer`` +
  ``load_viewer`` and binds the resulting ``Viewer`` to a ContextVar.
- The audit wrapper (``audit.py``) — writes to the same ``audit_logs``
  table UM owns, with the agent_* fields extracted from the request.
- The MCP permission catalog (``permissions.py``) — codes
  ``mcp:tools:invoke`` / ``mcp:prompts:get`` / ``mcp:resources:read`` /
  ``mcp:agents:read``.
- Two built-in tools (``tools/echo.py``, ``tools/user_directory.py``)
  that double as runnable examples and as the test surface for the
  auth / audit / permission wiring.

What this module does NOT own
-----------------------------

- Auth tokens (they live in user-management's ``auth_tokens`` table —
  no separate ``mcp_tokens``).
- The ``Viewer`` dataclass (it IS user-management's, used as-is).
- The OAuth 2.1 provider (it IS user-management's ``app/auth/oauth21.py``;
  this template's ``main.py`` mounts it under ``/mcp/oauth`` via a new
  ``mount_path`` parameter, with the empty default preserving UM behavior).
- Any new database tables in v1 (the 0003 migration is structurally a
  no-op; the chain anchor exists so future MCP-owned tables have a
  natural home).

The single public entry point used by the parent ``main.py`` is
:func:`app.mcp.module.register`.
"""

from app.mcp.module import register

__all__ = ["register"]
