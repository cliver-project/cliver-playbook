"""The MCP auth gate: bearer verification + per-request context binding.

Wrapped around the SDK's streamable-http endpoint by ``api/streamable.py``,
which passes the gate *as* the route's endpoint (FastAPI's router inclusion
rebuilds plain routes from ``route.endpoint``, so the gate has to be part of
the endpoint object rather than wrapped on it afterwards — ADR-0017). One
middleware, two modes, selected per request by ``settings.mcp.auth_enabled``:

- **OFF (the default)**: no credential is required or read. An
  :class:`~cliver_playbook.app.mcp.context.AnonymousViewer` is bound so downstream
  permission checks fail closed (``has()`` is always False) — auth being
  off must not silently grant permissions, it just means "no identity".

- **ON**: the request must carry ``Authorization: Bearer <token>``. The
  token resolves through user-management's kind-agnostic
  :func:`~cliver_playbook.app.user.auth.tokens.verify_bearer` — web sessions, static tokens
  and OAuth access tokens all work, because they all live in the same
  ``auth_tokens`` table with the same revocation path (a Web force-logout
  kills the agent's token too, which is the point of sharing the table).
  A resolved token loads the same :class:`~cliver_playbook.app.user.auth.dependencies.Viewer`
  the Web's ``get_current_user`` builds (fresh roles + permissions per
  request), so mid-session permission changes apply to the next tool
  call. ``must_change_password`` viewers are blocked with 403, mirroring
  the Web's server-enforced rotation gate.

Rejections answer 401 with an RFC 9728 ``WWW-Authenticate`` header
pointing at this service's protected-resource metadata (mounted by
``mount_oauth_routes`` at the root; its ``resource`` value is exactly
this MCP endpoint, ``{base}/mcp``). Every rejection lands an audit row
(``mcp.auth.reject``) — the agent's identity headers are recorded even
for unauthenticated callers, so brute-force attempts leave a trail of
*which machine* tried.

In BOTH modes the gate binds the request scope and the agent identity
(audit reads them regardless of auth), and passes non-HTTP scopes
(lifespan) straight through.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.responses import JSONResponse

from cliver_playbook.app.basic.db.session import open_session
from cliver_playbook.app.mcp.audit import write_auth_rejection
from cliver_playbook.app.mcp.context import (
    AgentIdentity,
    AnonymousViewer,
    bind_agent,
    bind_request,
    bind_viewer,
    build_agent_identity,
)
from cliver_playbook.app.mcp.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, load_viewer
from cliver_playbook.app.user.auth.tokens import verify_bearer

logger = logging.getLogger("cliver_playbook.app.mcp.auth")

# The protected-resource metadata path every RFC 9728 client probes.
_PRM_PATH = "/.well-known/oauth-protected-resource"


def _request_headers(scope: dict[str, Any]) -> dict[str, str]:
    """Decode ASGI headers (latin-1, lower-cased keys) once per request."""
    return {
        k.decode("latin-1").lower(): v.decode("latin-1", "replace")
        for k, v in scope.get("headers", [])
    }


def _agent_from_headers(headers: dict[str, str]) -> AgentIdentity:
    """Thin adapter over :func:`cliver_playbook.app.mcp.context.build_agent_identity`,
    which owns the normalisation rules shared with the stdio
    environment-variable path."""
    return build_agent_identity(
        agent_type=headers.get("x-mcp-agent-type", ""),
        agent_id=headers.get("x-mcp-agent-id", ""),
    )


async def resolve_viewer(token: str) -> Viewer | None:
    """Resolve a bearer token to the fresh Viewer the Web would build, or None.

    Kind-agnostic on purpose: the token may be a Web session, a static
    MCP token or an OAuth access token — they all live in ``auth_tokens``
    and go through the same revocation predicate, so a Web force-logout
    kills the agent's access too. Roles and permissions are loaded per
    call, so mid-session changes apply to the next tool call.

    Policy stays with the caller: the HTTP gate answers 403 on
    ``must_change_password``, the stdio bootstrap refuses to start —
    this function only resolves. Shared by both transports.
    """
    if not token:
        return None
    async with open_session() as db:
        row = await verify_bearer(db, token)
        if row is None:
            return None
        return await load_viewer(db, row.user_id, token_id=row.id)


def _bearer_from_headers(headers: dict[str, str]) -> str:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


class MCPGateMiddleware:
    """ASGI middleware around the MCP endpoint (see module docstring)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = _request_headers(scope)
        # Bound in both modes: audit records the agent and the wire origin
        # even when nobody authenticated.
        bind_request(scope)
        bind_agent(_agent_from_headers(headers))

        if not settings.mcp.auth_enabled:
            bind_viewer(AnonymousViewer())
            await self.app(scope, receive, send)
            return

        token = _bearer_from_headers(headers)
        if not token:
            await self._reject(
                scope,
                receive,
                send,
                error="missing_token",
                description="Authorization: Bearer required (mcp.auth_enabled is on)",
            )
            return

        viewer = await resolve_viewer(token)
        if viewer is None:
            # Unknown/expired/revoked token, or the user vanished/was
            # deactivated after issuance — all get the same answer.
            await self._reject(
                scope,
                receive,
                send,
                error="invalid_token",
                description="Bearer token is unknown, expired or revoked",
            )
            return
        if viewer.must_change_password:
            await self._reject(
                scope,
                receive,
                send,
                error="must_change_password",
                description="Password rotation required before any MCP access",
                status=403,
            )
            return

        bind_viewer(viewer)
        await self.app(scope, receive, send)

    async def _reject(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        *,
        error: str,
        description: str,
        status: int = 401,
    ) -> None:
        """Answer the rejection and audit it. Best-effort on the audit side."""
        response_headers: dict[str, str] = {}
        if status == 401:
            # RFC 9728: point the client at the protected-resource metadata
            # so it can discover the authorization server (dynamic client
            # registration included). The base matches what the OAuth
            # routes themselves advertise (explicit issuer setting or the
            # loopback default) — deriving from this request's Host instead
            # would disagree with the mounted metadata behind proxies.
            from cliver_playbook.app.user.auth.oauth21 import load_oauth_settings

            prm_url = load_oauth_settings().base_url + _PRM_PATH
            response_headers["WWW-Authenticate"] = (
                f'Bearer resource_metadata="{prm_url}", error="{error}"'
            )
        await write_auth_rejection(error=error, description=description)
        response = JSONResponse(
            {"error": error, "error_description": description},
            status_code=status,
            headers=response_headers,
        )
        await response(scope, receive, send)
