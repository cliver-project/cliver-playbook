from mcp.server.fastmcp import FastMCP

# This provides a FastMCP instance with customized configuration
#
mcp : FastMCP
def initialize_mcp(config: dict = None):
    global mcp
    if config is None:
        config = {}
    mcp = FastMCP(
        name=config.get("name", "MCP-X"),
        instructions=config.get("instructions"),
        stateless_http=config.get("stateless_http", False),
        json_response=config.get("json_response", False),
        host=config.get("host", "0.0.0.0"),
        port=config.get("port", 8000),
        log_level=config.get("log_level", "INFO"),
        on_duplicate_tools=config.get("on_duplicate_tools", "warn"),
    )
