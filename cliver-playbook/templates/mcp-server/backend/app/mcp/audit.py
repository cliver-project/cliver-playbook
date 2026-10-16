"""MCP audit wrapper: thin layer over user-management's ``write_audit``.

Every tool / prompt / resource call lands one row in the existing
``audit_logs`` table. The MCP delta on top of UM's row is the
``event`` name (``mcp.tool.call`` / ``mcp.prompt.get`` /
``mcp.resource.read``) and the agent_* fields extracted from the
request context. ``user_id`` is set when an authenticated viewer's
``user_id`` is known; anonymous rows carry ``user_id=None`` but the
agent_* fields are still present, so a single log view answers
"who called what, from which agent, with which token identity".

Failure policy: a write_audit that raises is logged at WARNING and
swallowed. The tool call's own success/failure is the primary record;
audit is best-effort. This matches ai-gov's mcp_server/audit.py and
the design rationale is identical (a transient DB hiccup must not
break an otherwise-successful tool call).
"""

from __future__ import annotations

import logging
from typing import Any

from app.auth.audit import write_audit
from app.db.session import SessionLocal
from app.mcp.context import AnonymousViewer, current_agent, current_request, current_viewer

logger = logging.getLogger("mcp.audit")

# Hard cap on the args we record per audit row. Keeps audit_logs from
# growing unbounded when a tool receives a large payload, and matches
# the ai-gov implementation's truncation policy. 200 chars / object is
# enough to identify the call without leaking the whole input.
_MAX_ARG_CHARS = 200


def _truncate(value: Any) -> Any:
    """Stringify + truncate any value for the audit row's ``detail`` field.

    Strings are clipped to ``_MAX_ARG_CHARS``; nested dicts and lists
    are recursed into once and clipped the same way. Anything that
    cannot be coerced to a string is replaced with its repr. The goal
    is a stable, predictable shape that the audit viewer can render.
    """
    if isinstance(value, str):
        return value[:_MAX_ARG_CHARS]
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value[:50]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)[:_MAX_ARG_CHARS]


def _request_meta() -> tuple[str, str]:
    """Best-effort ip + user-agent from the current request scope.

    For HTTP: the standard ``client`` / ``headers`` ASGI scope fields,
    with X-Forwarded-For first (the FastAPI middleware re-binds the
    scope, so a request behind a proxy reports the proxy ip here — the
    audit row will say the proxy, not the agent, which is fine for the
    purposes of "where did the call come from on the wire").

    For stdio: returns ``("stdio", "")`` so the audit row carries an
    explicit transport tag rather than empty strings.
    """
    scope = current_request()
    if scope.get("type") == "stdio":
        return ("stdio", "")

    headers = scope.get("headers") or []
    user_agent = ""
    for k, v in headers:
        if k == b"user-agent":
            user_agent = v.decode("latin-1", errors="replace")
            break

    xff = ""
    for k, v in headers:
        if k == b"x-forwarded-for":
            xff = v.decode("latin-1", errors="replace")
            break
    ip = xff.split(",", 1)[0].strip() if xff else ""
    if not ip:
        client = scope.get("client") or ("", 0)
        ip = client[0] if client else ""
    return (ip, user_agent)


def _sanitize_actor() -> tuple[int | None, str]:
    """Pull the actor (user_id, username) from the current viewer.

    Anonymous viewers and unbound calls produce (None, "") — the row
    still records the agent_* fields, so the audit can still answer
    "which machine did this" even when no user was authenticated.
    """
    try:
        viewer = current_viewer()
    except RuntimeError:
        return (None, "")
    if isinstance(viewer, AnonymousViewer) or viewer.user_id is None:
        return (None, "")
    return (viewer.user_id, viewer.username)


async def write_tool_audit(
    *,
    method: str,  # "tools/call" | "prompts/get" | "resources/read"
    target: str,  # tool / prompt / resource name
    args: dict | None = None,
    ok: bool,
    error: str = "",
    duration_ms: int = 0,
    extra_detail: dict | None = None,
) -> None:
    """Write one audit row for an MCP call. Best-effort; never raises."""
    event = f"mcp.{method.replace('/', '.')}"  # "mcp.tools.call" etc.
    user_id, username = _sanitize_actor()
    agent = current_agent()
    ip, user_agent = _request_meta()

    detail: dict[str, Any] = {
        "args": _truncate(args or {}),
        "duration_ms": max(0, int(duration_ms)),
        "agent_type": agent.normalised_type(),
        "agent_id": agent.truncated_id(128),
    }
    if extra_detail:
        detail.update(_truncate(extra_detail))

    try:
        async with SessionLocal() as db:
            await write_audit(
                db,
                event=event,
                user_id=user_id,
                username=username,
                target=target,
                ok=ok,
                error=error,
                detail=detail,
                ip=ip,
                user_agent=user_agent,
            )
            await db.commit()
    # Broad catch is the contract: any failure in the audit path (DB down,
    # constraint, driver error) must not propagate into the tool result.
    except Exception as exc:  # noqa: BLE001  # pragma: no cover — best-effort
        logger.warning("MCP audit write failed for %s/%s: %s", method, target, exc)


async def write_auth_rejection(*, error: str, description: str = "") -> None:
    """Audit row for a gate rejection (401/403): event ``mcp.auth.reject``.

    Same wrapper, same best-effort policy — a DB hiccup must not turn a
    clean 401 into a 500. The agent identity headers are recorded even
    though nobody authenticated: brute-force attempts should leave a
    trail of *which machine* tried.
    """
    error_text = f"{error}: {description}" if description else error
    await write_tool_audit(method="auth/reject", target="gate", ok=False, error=error_text)
