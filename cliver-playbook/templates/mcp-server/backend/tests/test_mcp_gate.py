"""The auth gate — 401 shapes, context binding, rejection audit rows.

Two invocation styles, on purpose:

- **Direct ASGI invocation** (hand-built scope + stub inner app) for the
  binding behaviour: the stub captures the ContextVars the gate bound,
  which is exactly the contract tool functions rely on. No SDK, no
  lifespan, no server needed.

- **Full HTTP through the app** (httpx ASGITransport) for the rejection
  paths: the gate short-circuits before the streamable-http machinery,
  so no lifespan is required and the whole routing/middleware stack is
  exercised. Auth-ON full end-to-end (valid token + initialize) needs
  the running session manager and therefore the booted TestClient —
  that combination is covered by the transport tests (M6) where loops
  are consistent.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from starlette.responses import PlainTextResponse

from app.core.config import settings
from app.mcp.auth import MCPGateMiddleware
from app.mcp.context import AnonymousViewer, current_agent, current_viewer

MCP_ACCEPT = "application/json, text/event-stream"


# ---------------------------------------------------------------------------
# direct-invocation helpers
# ---------------------------------------------------------------------------


async def _receive() -> dict[str, Any]:
    """ASGI receive channel yielding one empty request body.

    Passed as the callable itself (never invoked here — responses on these
    paths never read the body), so no orphaned coroutine is created.
    """
    return {"type": "http.request", "body": b"", "more_body": False}


class _SendCollector:
    """Collects raw ASGI messages so status/headers can be asserted."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def _scope(headers: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": settings.mcp.mount_path,
        "raw_path": settings.mcp.mount_path.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 1111),
        "headers": headers,
    }


def _capturing_app(captured: dict[str, Any]) -> Any:
    """Stub inner app that records the bound context and answers 200."""

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        captured["viewer"] = current_viewer()
        captured["agent"] = current_agent()
        await PlainTextResponse("ok")(scope, receive, send)

    return inner


async def _latest_reject_row(db: Any) -> Any:
    from sqlalchemy import select

    from app.models.entities import AuditLog

    rows = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "mcp.auth.reject")))
        .scalars()
        .all()
    )
    assert rows, "expected an mcp.auth.reject audit row"
    return rows[-1]


# ---------------------------------------------------------------------------
# auth OFF (template default)
# ---------------------------------------------------------------------------


async def test_gate_off_binds_anonymous_viewer_and_normalised_agent():
    """OFF mode: anonymous viewer bound (has() always False — auth off must
    not silently grant permissions) and the agent identity normalised."""
    captured: dict[str, Any] = {}
    gate = MCPGateMiddleware(_capturing_app(captured))
    send = _SendCollector()
    await gate(
        _scope(
            [
                (b"x-mcp-agent-type", b"Claude-Code"),
                (b"x-mcp-agent-id", b"inst-1"),
            ]
        ),
        _receive,
        send,
    )
    assert isinstance(captured["viewer"], AnonymousViewer)
    assert captured["viewer"].has("mcp:tools:invoke") is False
    assert captured["agent"].agent_type == "claude-code"
    assert captured["agent"].agent_id == "inst-1"
    assert send.messages[0]["status"] == 200


async def test_gate_agent_type_whitelisted_to_unknown():
    """A self-reported type outside the configured whitelist lands on
    'unknown' at BIND time — audit rows can never carry rogue strings."""
    captured: dict[str, Any] = {}
    gate = MCPGateMiddleware(_capturing_app(captured))
    await gate(
        _scope([(b"x-mcp-agent-type", b"rogue-agent")]),
        _receive,
        _SendCollector(),
    )
    assert captured["agent"].agent_type == "unknown"


# ---------------------------------------------------------------------------
# auth ON — rejections over full HTTP
# ---------------------------------------------------------------------------


async def test_gate_on_missing_token_401_with_www_authenticate(client, db, monkeypatch):
    monkeypatch.setattr(settings.mcp, "auth_enabled", True)
    resp = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "gate-test", "version": "0"},
            },
        },
        headers={"Accept": MCP_ACCEPT},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_token"
    www = resp.headers.get("www-authenticate", "")
    assert www.startswith("Bearer resource_metadata=")
    assert "/.well-known/oauth-protected-resource" in www
    assert 'error="missing_token"' in www

    row = await _latest_reject_row(db)
    assert row.error.startswith("missing_token")
    assert row.detail["agent_type"] == "unknown"  # no headers sent


async def test_gate_on_invalid_token_401_audited(client, db, monkeypatch):
    monkeypatch.setattr(settings.mcp, "auth_enabled", True)
    resp = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer not-a-real-token", "Accept": MCP_ACCEPT},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"

    row = await _latest_reject_row(db)
    assert row.error.startswith("invalid_token")


# ---------------------------------------------------------------------------
# auth ON — acceptance (direct invocation: binding contract)
# ---------------------------------------------------------------------------


async def test_gate_on_binds_viewer_and_forwards(db, monkeypatch):
    """A valid token resolves to the same Viewer the Web builds: fresh
    roles + permissions, so role changes apply on the next tool call."""
    from app.auth.tokens import issue_web_token
    from tests.helpers import seed_admin

    monkeypatch.setattr(settings.mcp, "auth_enabled", True)
    user_id = await seed_admin(db)
    token = await issue_web_token(db, user_id=user_id)
    await db.commit()  # the gate reads through its own session

    captured: dict[str, Any] = {}
    gate = MCPGateMiddleware(_capturing_app(captured))
    send = _SendCollector()
    await gate(
        _scope(
            [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-mcp-agent-type", b"workbuddy"),
            ]
        ),
        _receive,
        send,
    )
    assert send.messages[0]["status"] == 200
    viewer = captured["viewer"]
    assert viewer.user_id == user_id
    assert viewer.has("mcp:tools:invoke") is True  # seeded admin holds all catalog perms
    assert captured["agent"].agent_type == "workbuddy"


async def test_resolve_viewer_token_paths(db):
    """resolve_viewer is the shared token→Viewer plumbing both transports
    use: empty and unknown tokens resolve to None, a valid token to the
    fresh Viewer the Web would build (so role changes apply on the next
    call)."""
    from app.auth.tokens import issue_web_token
    from app.mcp.auth import resolve_viewer
    from tests.helpers import seed_admin

    assert await resolve_viewer("") is None
    assert await resolve_viewer("not-a-real-token") is None

    user_id = await seed_admin(db)
    token = await issue_web_token(db, user_id=user_id)
    await db.commit()

    viewer = await resolve_viewer(token)
    assert viewer is not None
    assert viewer.user_id == user_id
    assert viewer.token_id is not None
    assert viewer.has("mcp:tools:invoke")


async def test_gate_on_revoked_token_rejected(db, monkeypatch):
    """Force-logout semantics: revoking the token row kills MCP access on
    the very next request (same table, same predicate as the Web)."""
    from datetime import datetime

    from sqlalchemy import update

    from app.auth.tokens import issue_web_token
    from app.models.entities import AuthToken
    from tests.helpers import seed_admin

    monkeypatch.setattr(settings.mcp, "auth_enabled", True)
    user_id = await seed_admin(db)
    token = await issue_web_token(db, user_id=user_id)
    await db.commit()
    await db.execute(
        update(AuthToken).where(AuthToken.user_id == user_id).values(revoked_at=datetime.now(UTC))
    )
    await db.commit()

    gate = MCPGateMiddleware(_capturing_app({}))
    send = _SendCollector()
    await gate(
        _scope([(b"authorization", f"Bearer {token}".encode())]),
        _receive,
        send,
    )
    assert send.messages[0]["status"] == 401


async def test_gate_on_must_change_password_403(db, monkeypatch):

    from app.auth.passwords import hash_password
    from app.auth.tokens import issue_web_token
    from app.models.entities import User

    monkeypatch.setattr(settings.mcp, "auth_enabled", True)
    user = User(
        username="rotate-me",
        password_hash=hash_password("irrelevant"),
        display_name="Rotate Me",
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    token = await issue_web_token(db, user_id=user.id)
    await db.commit()

    gate = MCPGateMiddleware(_capturing_app({}))
    send = _SendCollector()
    await gate(
        _scope([(b"authorization", f"Bearer {token}".encode())]),
        _receive,
        send,
    )
    assert send.messages[0]["status"] == 403
