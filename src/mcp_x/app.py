from dotenv import load_dotenv
import click
import os
import uvicorn
from fastapi import FastAPI
from mcp_x.mcp_server_instance import initialize_mcp
from mcp_x.mcp_server import MCPServer
import yaml

# Loads .env
load_dotenv()

#
# Run it: uvicorn mcp_x.app:app --host 0.0.0.0 --port 8000
#

class MCPApp:
    def __init__(self, mcp: MCPServer):
        self.host = "localhost"
        self.port = 8080
        self.debug = os.environ.get("DEBUG") == "True"
        self.mcp = mcp
        self.app = FastAPI()

    def start(self):
        self.app.mount("/mcp", self.mcp.get_mcp().streamable_http_app())
        uvicorn.run(self.app, host=self.host, port=self.port)

@click.command(name="mcp_x", help="Start mcp server")
@click.option(
    "--config",
    "-c",
    type=str,
    required=False,
    default="config.yaml",
    help="The config file for the MCP server",
)
def main(config: str) -> None:
    cfg = {"name": "MCP-X", "stateless_http": True}
    if os.path.exists(config):
        data = yaml.safe_load(open(config))
        cfg.update(data.get("mcp", {}))
    else:
        print("Config file not found")
    initialize_mcp(config = cfg)
    mcp_server = MCPServer(config=cfg)
    mcp_server.loads_mcp_capabilities()
    app = MCPApp(mcp_server)
    app.start()

if __name__ == "__main__":
    main()
