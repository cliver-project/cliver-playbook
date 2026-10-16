"""MCP auth gate — ASGI middleware that runs in front of the streamable-http
sub-app.

M1 stub: the class exists with the right surface so the parent
``subapp.py`` can reference it in M2, but the body raises
:class:`NotImplementedError` so a wrong import / accidental
mount in M0 does not silently bypass authentication. M3 fills in the
real implementation:

- Decodes the bearer token from the ``Authorization`` header (HTTP) or
  ``MCP_BEARER_TOKEN`` env var (stdio).
- Calls user-management's :func:`app.auth.tokens.verify_bearer` to
  resolve the token row, then :func:`app.auth.dependencies.load_viewer`
  to materialise the :class:`Viewer` from the database. Both raise
  ``None`` on failure; the gate returns 401 with the RFC 9728
  ``WWW-Authenticate`` header pointing at the OAuth 2.1 AS metadata
  (when auth_enabled is on) and writes an audit row tagged
  ``mcp.auth.rejected``.
- Binds the resolved viewer + the agent identity parsed from the
  ``X-MCP-Agent-Type`` / ``X-MCP-Agent-Id`` headers into the
  :mod:`app.mcp.context` ContextVars so the tool function body can
  read them via :func:`current_viewer` / :func:`current_agent`.

The middleware is *only* mounted when ``settings.mcp.auth_enabled`` is
true. When false, the gate is not in the ASGI chain at all — the
streamable-http app sees a normal request and the tool body reads
:func:`current_viewer` to find an :class:`AnonymousViewer`.
"""

from __future__ import annotations

from typing import Any


class MCPGateMiddleware:
    """Bearer-token ASGI gate for ``/mcp/*`` requests.

    M1: placeholder; the real implementation lands in M3 and is
    gated on ``settings.mcp.auth_enabled``. M2 may construct an
    instance of this class as part of the subapp wiring — it just
    must not run yet, so ``__call__`` raises until M3 lands.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        raise NotImplementedError(
            "MCPGateMiddleware is not implemented yet — Phase 3 step M3. "
            "Until then, run with settings.mcp.auth_enabled=false (the "
            "default) so the middleware is never mounted."
        )
        # Unreachable; the raise above is the whole point. The block
        # below is here only so type checkers and the inner-app wiring
        # see the expected call signature without complaining.
        await self._inner(scope, receive, send)  # pragma: no cover
