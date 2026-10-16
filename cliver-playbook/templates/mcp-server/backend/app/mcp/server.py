"""The MCP server singleton.

M1: construct the :class:`mcp.server.mcpserver.MCPServer` instance and
expose it as a module-level singleton. M4 registers the built-in
tools (echo + user_directory); M5+M6 wire audit + permission metadata
into each tool's wrapper.

The server's ``instructions`` string is the short identity line the
MCP client shows in its UI when listing servers. Project authors
override it via a future ``settings.mcp.instructions`` field; for
now the default is the template's own name so the UI says
``cliver-app-mcp``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

SERVER_NAME = "cliver-app-mcp"

mcp = MCPServer(
    name=SERVER_NAME,
    instructions=(
        "MCP server for the cliver-app template. Tools / prompts / "
        "resources are registered by the app.mcp.tools package at "
        "process start. See the per-tool docstrings for inputs."
    ),
)
