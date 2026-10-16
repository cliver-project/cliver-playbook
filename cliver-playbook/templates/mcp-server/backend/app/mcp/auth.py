"""The MCP auth gate: bearer verification + per-request context binding.

Wrapped around the SDK's streamable-http endpoint by ``subapp.py`` (in
place, on the route's ASGI app — the mount and lifespan wiring stay
untouched). One middleware, two modes, selected per request by
``settings.mcp.auth_enabled``:

- **OFF (template default)**: no credential is required or read. An
  :class:`~app.mcp.context.AnonymousViewer` is bound so downstream
  permission checks fail closed (``has()`` is always False) — auth being
  off must not silently grant permissions, it just means "no identity".

- **ON**: the request must carry ``Authorization: Bearer <token>``. The
  token resolves through user-management's kind-agnostic
  :func:`~app.auth.tokens.verify_bearer` — web sessions, static tokens
  and OAuth access tokens all work, because they all live in the same
  ``auth_tokens`` table with the same revocation path (a Web force-logout
  kills the agent's token too, which is the point of sharing the table).
  A resolved token loads the same :class:`~app.auth.dependencies.Viewer`
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

from app.auth.dependencies import load_viewer
from app.auth.tokens import verify_bearer
from app.core.config import settings
from app.db.session import SessionLocal
from app.mcp.audit import write_auth_rejection
from app.mcp.context import (
    AgentIdentity,
    AnonymousViewer,
    bind_agent,
    bind_request,
    bind_viewer,
)

logger = logging.getLogger("mcp.auth")

# The protected-resource metadata path every RFC 9728 client probes.
_PRM_PATH = "/.well-known/oauth-protected-resource"


def _request_headers(scope: dict[str, Any]) -> dict[str, str]:
    """Decode ASGI headers (latin-1, lower-cased keys) once per request."""
    return {
        k.decode("latin-1").lower(): v.decode("latin-1", "replace")
        for k, v in scope.get("headers", [])
    }


def _agent_from_headers(headers: dict[str, str]) -> AgentIdentity:
    """Build the normalised agent identity from the request headers.

    Raw values are lower-cased, whitelist-filtered and truncated HERE so
    every downstream reader (audit rows, tool context) sees the same
    normalised form — no reader re-normalises with its own rules. An
    empty whitelist means "accept any string" (dev default).
    """
    raw = AgentIdentity(
        agent_type=headers.get("x-mcp-agent-type", ""),
        agent_id=headers.get("x-mcp-agent-id", ""),
    )
    whitelist = set(settings.mcp.agent_type_whitelist) or None
    return AgentIdentity(
        agent_type=raw.normalised_type(whitelist),
        agent_id=raw.truncated_id(settings.mcp.agent_id_max_length),
    )


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

        async with SessionLocal() as db:
            row = await verify_bearer(db, token)
            viewer = (
                await load_viewer(db, row.user_id, token_id=row.id) if row is not None else None
            )
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
            from app.auth.oauth21 import load_oauth_settings

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
