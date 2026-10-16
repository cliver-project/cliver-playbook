"""MCP tool collection.

M1: empty package. M4 registers the built-in demos (``echo`` +
``user_directory``) by importing them here and calling ``register_*``
on the package-level :data:`app.mcp.server.mcp` server. Project
authors who add their own tools either drop a new file in this
package and import it here, or call :func:`app.mcp.server.mcp.tool`
directly from their own module — both paths compose with the audit
and permission wrappers (M5) and the stdio transport (M6).
"""
