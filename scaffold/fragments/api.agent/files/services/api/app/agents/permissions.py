"""Per-agent permission callback over AgentCore tool calls.

The default ``scoped`` mode is defense in depth: a builtin tool must be in the
agent's toolkit (and in its optional allow-list), and an MCP tool's server must
be in the run's selected MCP set. ``read_only`` additionally denies ASK-category
tools. ``allow_all`` preserves the legacy opt-out for projects that supply
their own policy at a higher layer.
"""

from __future__ import annotations

from cliver_core.policy import Decision, ToolCallContext, ToolCategory

from app.agents.contracts import AgentContext, AgentToolkit
from app.agents.mcp import select_mcp_servers

PERMISSION_MODES = frozenset({"scoped", "read_only", "allow_all"})


def build_permission_callback(toolkit: AgentToolkit, context: AgentContext):
    """Return a synchronous AgentCore permission callback for this run."""
    mode = str(context.resources.get("tool_permission_mode") or toolkit.permission_mode or "scoped")
    declared = {tool.name for tool in toolkit.tools if getattr(tool, "name", "")}
    allowed_tools = set(toolkit.allowed_tools) if toolkit.allowed_tools else declared
    selected_mcp = set(select_mcp_servers(context, toolkit) or [])

    def callback(call: ToolCallContext) -> Decision:
        if mode == "allow_all":
            return Decision.allow()
        if mode == "read_only":
            if call.category is ToolCategory.ASK:
                return Decision.deny("this agent is running in read-only mode")
            return Decision.allow()
        if mode != "scoped":
            return Decision.deny("unknown tool permission mode")
        if call.server is not None:
            if call.server in selected_mcp:
                return Decision.allow()
            return Decision.deny("this MCP server is not allowed for the agent")
        if call.tool_name in allowed_tools:
            return Decision.allow()
        return Decision.deny("this tool is not declared by the agent")

    return callback
