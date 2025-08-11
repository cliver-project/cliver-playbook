from mcp_x.mcp_server_instance import mcp
from jinja2 import Environment, FileSystemLoader

# config will be injected when loading by the mcp_server
# Note that the config cannot be used outside the methods
# because it has not been initialized when loading this module
config: dict

# Set up Jinja2 to load templates from the prompts/ directory
template_env = Environment(loader=FileSystemLoader("prompts"))

# Example resource: Retrieve a raw prompt template content by name
@mcp.resource("resource://{name}")
def get_resource(name: str) -> str:
    """
    Return the Jinja2 template text for a given prompt name (no variables filled).
    """
    template = template_env.get_template(f"{name}.j2")
    return template.render()

