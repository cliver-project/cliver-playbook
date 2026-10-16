"""The MCP package's HTTP surface: the protocol endpoint and its Web-facing API.

Two routers, one prefix policy each:

- ``streamable`` — the protocol endpoint at the fixed ``/mcp``. This is the
  route agents speak to, and it is a plain route in a router like any other
  (ADR-0017): no mounted sub-application, no catch-all.
- ``discovery`` — the ``/api/v1/mcp`` routes the Web UI reads (public facts +
  the agent-activity view). Ordinary prefixed API routes.

Both are exposed through ``routes.ROUTERS``; nothing here is imported for its
side effects.
"""
