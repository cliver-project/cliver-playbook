"""The MCP server singleton.

Construct the :class:`mcp.server.mcpserver.MCPServer` instance and expose
it as a module-level singleton. Built-in tools (``cliver_playbook/app/mcp/tools/``)
register on it through the SDK's ``@mcp.tool()`` decorator when
``register_default_tools()`` imports them; the audit + permission
cross-cutting work lives in :mod:`cliver_playbook.app.mcp.toolkit`'s decorators.

The server's ``instructions`` string is the short identity line the
MCP client shows in its UI when listing servers. It is a module
constant on purpose — an operator-visible string with no deployment
variance; rename it (or ``SERVER_NAME``) when adapting this package to
a product.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

SERVER_NAME = "cliver-app-mcp"

mcp = MCPServer(
    name=SERVER_NAME,
    instructions=(
        "MCP server for cliver-app. Tools / prompts / "
        "resources are registered by the cliver_playbook.app.mcp.tools package at "
        "process start. See the per-tool docstrings for inputs."
    ),
)
