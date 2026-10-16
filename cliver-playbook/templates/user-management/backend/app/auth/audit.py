"""Unified audit trail writer.

Every security-relevant event lands in `audit_logs`: logins (success and
failure), password changes, admin operations, and (in the mcp-server template)
tool calls. One table with a generic shape beats per-domain log tables — a
compliance review asks cross-cutting questions like "everything operator X did
this month".

`write_audit` runs inside the caller's transaction on purpose: an admin
operation that cannot record its own audit row should fail, not silently
proceed unaudited.

Detail payloads pass through `sanitize_detail`, which redacts keys that look
like secrets and truncates long strings — audit rows are written with less
privilege discipline than secrets storage and must never become a credential
dump (the classic leak: hashing a token into audit `detail` next to the
plaintext that arrived in headers).
"""

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog

# Substring markers — a key containing any of these has its value redacted.
_SENSITIVE_MARKERS = ("password", "secret", "token", "authorization", "cookie", "credential")
_MAX_STR = 500
_MAX_DEPTH = 4


def _redacted(value: str) -> str:
    return f"<redacted:{len(value)} chars>"


def sanitize_detail(value: Any, depth: int = 0) -> Any:
    """Make a value safe to persist in an audit row.

    - dict keys containing a sensitive marker -> value replaced with a length hint
    - strings truncated to _MAX_STR chars
    - containers beyond _MAX_DEPTH collapse to a type marker (defends against
      pathological nesting from caller-supplied JSON)
    """
    if depth > _MAX_DEPTH:
        return "<max-depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if any(marker in key.lower() for marker in _SENSITIVE_MARKERS):
                out[key] = _redacted(str(v))
            else:
                out[key] = sanitize_detail(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize_detail(v, depth + 1) for v in value]
    if isinstance(value, str) and len(value) > _MAX_STR:
        return value[:_MAX_STR] + f"...<truncated {len(value) - _MAX_STR} chars>"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _client_ip(request: Request | None) -> str:
    """Best-effort client IP: first X-Forwarded-For hop, else the socket peer.

    Behind a reverse proxy the socket peer is the proxy; X-Forwarded-For is the
    conventional fix. The value is informational (audits, lockout telemetry) —
    it is attacker-controllable when not behind a trusted proxy, so nothing
    security-critical may branch on it alone.
    """
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


async def write_audit(
    db: AsyncSession,
    *,
    event: str,
    user_id: int | None = None,
    username: str = "",
    target: str = "",
    ok: bool = True,
    error: str = "",
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Append one audit row in the caller's transaction.

    Keep `event` names stable and dot-namespaced by domain ("auth.login",
    "admin.user.create", "mcp.tools.call") — the audit UI groups on them.

    Prefer `request` (ip/ua derived from it). The explicit `ip`/`user_agent`
    kwargs serve call sites that hold no Request object — the OAuth provider,
    whose methods the SDK invokes with a ContextVar-published meta instead.
    """
    db.add(
        AuditLog(
            user_id=user_id,
            username=(username or "")[:100],
            event=event[:64],
            target=(target or "")[:128],
            ok=ok,
            error=(error or "")[:500],
            detail=sanitize_detail(detail or {}),
            ip=_client_ip(request) or ip[:64],
            user_agent=((request.headers.get("user-agent", "") if request else "") or user_agent)[
                :256
            ],
        )
    )
    await db.flush()
