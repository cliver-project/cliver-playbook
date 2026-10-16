"""Per-request MCP state held in ContextVars.

Three independent slots, all set by the auth gate (M3) and read by tool
functions / the audit wrapper:

- :func:`current_viewer` — the user-management ``Viewer`` when auth is
  on, an :class:`AnonymousViewer` when auth is off. A tool that declares
  ``@require_perm("...")`` calls :meth:`AnonymousViewer.has` (always
  False) / :meth:`Viewer.has` (catalog lookup); auth-OFF therefore
  rejects perm-required tools by design — the gate flag is orthogonal
  to the permission system.

- :func:`current_agent` — the agent's self-identification
  (``X-MCP-Agent-Type`` / ``X-MCP-Agent-Id`` headers, or
  ``MCP_AGENT_TYPE`` / ``MCP_AGENT_ID`` env vars for stdio). The audit
  wrapper records both fields on every tool/prompt/resource call;
  ``unknown`` / ``""`` are honest defaults for callers that don't
  identify themselves.

- :func:`current_request` — the raw ASGI scope dict for the in-flight
  request, used by the audit wrapper to extract ``ip`` /
  ``user-agent`` and by the gate to write the WWW-Authenticate header
  on 401. For stdio transport, the scope is synthesized as
  ``{"type": "stdio", ...}`` so the audit row's ``ip`` field is
  ``"stdio"`` (rather than empty) — visible in the log as a deliberate
  "this row came from a stdio call".

The ContextVars live for the duration of the request. The MCP SDK's
streamable-http transport runs each call inside a per-request task
context, so the ContextVars reset between requests without explicit
teardown. The stdio transport runs every call inside a fresh task
spun off the stdin reader, same story.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.auth.dependencies import Viewer


@dataclass(frozen=True)
class AnonymousViewer:
    """The viewer when ``settings.mcp.auth_enabled`` is false.

    Distinct type from :class:`app.auth.dependencies.Viewer` so the
    type system (and a quick isinstance at the audit site) records
    "this row was written by an unauthenticated caller". ``has`` is
    always False: an anonymous caller never holds any permission,
    even when the tool would otherwise be marked public via
    ``@public_tool``. Agent identity is NOT mirrored here — it lives
    only in :class:`AgentIdentity`, a single source of truth.
    """

    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    role_codes: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    token_id: int | None = None

    def has(self, code: str) -> bool:
        return False


@dataclass(frozen=True)
class AgentIdentity:
    """Caller-side identity that travels with every request."""

    agent_type: str = "unknown"  # from X-MCP-Agent-Type / MCP_AGENT_TYPE
    agent_id: str = ""  # from X-MCP-Agent-Id / MCP_AGENT_ID

    def normalised_type(self, whitelist: set[str] | None = None) -> str:
        """Lower-case + truncate. Unknown values land on ``"unknown"`` so the
        audit row never carries attacker-controlled raw strings beyond the
        configured allowlist. ``whitelist`` is the configured
        ``settings.mcp.agent_type_whitelist`` — when None, no filtering."""
        t = (self.agent_type or "").strip().lower()[:32]
        if not t:
            return "unknown"
        if whitelist is not None and t not in whitelist:
            return "unknown"
        return t

    def truncated_id(self, max_length: int) -> str:
        return (self.agent_id or "")[:max_length]


_current_viewer: ContextVar[Viewer | AnonymousViewer | None] = ContextVar(
    "mcp_current_viewer", default=None
)
# Both defaults are None (B039: no mutable shared defaults); the
# accessors materialise a fresh anonymous identity / empty scope for
# unbound reads — callers see "no agent info" / "no request info"
# rather than having to None-check.
_current_agent: ContextVar[AgentIdentity | None] = ContextVar("mcp_current_agent", default=None)
_current_request: ContextVar[dict[str, Any] | None] = ContextVar(
    "mcp_current_request", default=None
)


def bind_viewer(viewer: Viewer | AnonymousViewer | None) -> None:
    """Set the viewer for the current task. M3 calls this from the gate."""
    _current_viewer.set(viewer)


def bind_agent(agent: AgentIdentity) -> None:
    _current_agent.set(agent)


def bind_request(scope: dict[str, Any]) -> None:
    _current_request.set(scope)


def current_viewer() -> Viewer | AnonymousViewer:
    """The current viewer. Raises RuntimeError if no gate ran (a tool called
    without an enclosing request, which would be a programming error)."""
    v = _current_viewer.get()
    if v is None:
        raise RuntimeError(
            "No viewer bound — caller path must be inside MCPGateMiddleware "
            "(HTTP) or the stdio bootstrap (stdio)."
        )
    return v


def current_agent() -> AgentIdentity:
    agent = _current_agent.get()
    return agent if agent is not None else AgentIdentity()


def current_request() -> dict[str, Any]:
    scope = _current_request.get()
    return scope if scope is not None else {}
