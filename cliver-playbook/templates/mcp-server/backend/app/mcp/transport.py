"""Standalone transports: the stdio bootstrap and the http runner.

The default deployment is in-process (the parent app's lifespan-composed
sub-app at ``settings.mcp.mount_path``). This module serves the two
standalone shapes:

- :func:`run_stdio` — the agent spawns ``python -m app.mcp`` and speaks
  JSON-RPC over stdin/stdout (the standard MCP stdio transport).
  Everything the HTTP gate does per request happens ONCE here, before
  the transport starts: the request scope tag (``{"type": "stdio"}``,
  which audit rows surface as ``ip="stdio"``), the agent identity
  (``MCP_AGENT_TYPE`` / ``MCP_AGENT_ID`` — the env equivalent of the
  HTTP headers), and — when auth is enabled — the viewer resolution
  (``MCP_BEARER_TOKEN``). The ContextVars set here are inherited by
  every task the transport spawns, so tool wrappers read exactly what
  they would read under HTTP.

- :func:`run_http` — serves the FULL parent application (API + MCP +
  OAuth) with uvicorn on a dedicated port. Full app, not just the MCP
  sub-app: the OAuth 2.1 authorize flow needs the API routes (the
  credentials endpoint) and redirects to the web frontend's login
  page, so an MCP-only listener would advertise a protected-resource
  metadata document whose flow dead-ends. This is a deployment shape
  (separate systemd unit / port), not a separate application; it
  shares the database with the Web process.

stdio auth policy — fail fast, never fail silently. With
``mcp.auth_enabled`` true there is exactly one long-lived session, so
the per-request 401/403 answers of the HTTP gate have no equivalent
mid-stream; the honest translation is refusing to start:

- no ``MCP_BEARER_TOKEN`` — every call would be rejected anyway;
- token unknown/expired/revoked — same;
- the token's user must change their password — the HTTP gate answers
  403 here; starting would serve a session that can never legitimately
  act.

stdout purity: stdout carries the protocol frames. Never add ``print``
to this path — logs go through ``logging`` (stderr by default), which
is safe.
"""

from __future__ import annotations

import os

from app.core.config import settings

__all__ = ["run_http", "run_stdio"]


async def run_stdio() -> None:
    """Bootstrap the single stdio session, then serve until stdin closes."""
    from app.mcp.auth import resolve_viewer
    from app.mcp.context import (
        AnonymousViewer,
        agent_identity_from_env,
        bind_agent,
        bind_request,
        bind_viewer,
    )
    from app.mcp.server import mcp
    from app.mcp.tools import register_default_tools

    register_default_tools()

    # Bound before the transport starts: the SDK spins up per-message
    # tasks from this context, so every tool call inherits these values.
    bind_request({"type": "stdio"})
    bind_agent(agent_identity_from_env())

    if settings.mcp.auth_enabled:
        token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "mcp.auth_enabled is true but MCP_BEARER_TOKEN is not set — "
                "every call would be rejected; refusing to start half-configured."
            )
        viewer = await resolve_viewer(token)
        if viewer is None:
            raise SystemExit("MCP_BEARER_TOKEN is unknown, expired or revoked — refusing to start.")
        if viewer.must_change_password:
            raise SystemExit(
                "The MCP_BEARER_TOKEN's user must change their password before "
                "any MCP access (the HTTP gate enforces the same rule with 403)."
            )
        bind_viewer(viewer)
    else:
        bind_viewer(AnonymousViewer())

    await mcp.run_stdio_async()


def run_http(*, host: str, port: int) -> None:
    """Serve the full application (API + MCP + OAuth) on a dedicated port."""
    import uvicorn

    # Import string, not the app object: uvicorn resolves it inside its
    # own process lifecycle, which keeps this call site free of the
    # parent app's assembly (and works under `python -m app.mcp` from
    # the backend directory thanks to the module-run path being on
    # sys.path).
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
