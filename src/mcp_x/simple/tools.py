from mcp_x.mcp_server_instance import mcp

# config will be injected when loading by the mcp_server
config: dict

# Example tool: Render a prompt template and (dummy) query a model
@mcp.tool(name="do_sum", title="Sum of 2 integers",
          description="Do the sum of 2 integers, return the result")
def do_sum(num1: int, num2: int) -> int:
    """
    @param num1 the number 1 to sum
    @param num2 the number 2 to sum
    @return the result of doing the sum of 2 integers.
    """
    return num1 + num2

