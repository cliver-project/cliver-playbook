from mcp_x.mcp_server_instance import mcp

# config will be injected when loading by the mcp_server
config: dict

# Example prompt: a static prompt template as a function
@mcp.prompt(title="EchoPrompt")
def echo_prompt(text: str) -> str:
    """
    A simple static prompt that just echoes user text.
    """
    return f"User said: {text}"
