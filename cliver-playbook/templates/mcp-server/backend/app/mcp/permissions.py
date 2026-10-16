"""MCP permission codes — convenience view over the shared catalog.

The four ``mcp:*`` :class:`~app.auth.permissions.Permission` rows live
directly in ``app/auth/permissions.py``'s ``PERMISSION_CATALOG`` (a static
edit made by this template; see INTEGRATION.md). They cannot be appended
at runtime: ``PERMISSION_CODES`` is imported by value into
``app.auth.dependencies`` / ``app.services.roles`` at import time, so a
runtime patch would never reach the ``require_perm`` guard.

This module only re-exports the code strings so the 0003 seed, the gate
and the tests can refer to them symbolically instead of repeating
string literals.
"""

from __future__ import annotations

MCP_PERMISSION_CODES: tuple[str, ...] = (
    "mcp:tools:invoke",
    "mcp:prompts:get",
    "mcp:resources:read",
    "mcp:agents:read",
)
