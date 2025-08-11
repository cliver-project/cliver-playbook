# mcp-x

This is a simple MCP Server which has the capabilities to:

- Tools:

  - Native Python code
  - Extended by loading py files from a specified directory.

- Prompt:

  - Text file based prompt templates with jinja2 support.
  - Retrieve prompt from a defined Vector DB

- Resources:

  - Specify directories from which they are served as resources.
  - Each file can be a resource based on its own MIME content type.

This MCP only starts with streamable SSE transport.

It can be running in a Docker container.
It can be running in a K8S platform.

The directories can be mounted from external storage.
