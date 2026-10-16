"""The MCP module's two /api routes: public discovery and gated activity.

``GET /api/v1/mcp/info`` exists so the playground never hardcodes the
mount path or the auth state: both are settings, and a page that guesses
them drifts silently. The endpoint is deliberately open (no token) — it
reports facts any socket can learn — so the first test runs on the
anonymous client fixture, which is exactly the property being pinned.

``GET /api/v1/mcp/calls`` is the agents page's data source and the
reason ``mcp:agents:read`` exists as a permission separate from
``audit:read``: an MCP operator watches agents without gaining the
identity audit trail, and vice versa. The tests below pin the
separation in both directions plus the server-side ``mcp.%`` event
predicate.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import write_audit
from app.auth.passwords import hash_password
from app.auth.tokens import issue_web_token
from app.core.config import settings
from app.mcp.server import SERVER_NAME
from app.models.entities import Role, RolePermission, User, UserRole


async def test_info_shape_is_public(client):
    resp = await client.get("/api/v1/mcp/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "server_name": SERVER_NAME,
        "mount_path": settings.mcp.mount_path,
        "auth_enabled": settings.mcp.auth_enabled,
    }


async def test_info_tracks_settings_at_request_time(client, monkeypatch):
    """The values are read per request, not frozen at import: an operator
    flipping auth on (env or app.yaml) must see the playground banner
    follow without a rebuild — and a custom mount path must be reported
    verbatim so the copy-paste endpoint URL stays correct."""
    monkeypatch.setattr(settings.mcp, "auth_enabled", True)
    monkeypatch.setattr(settings.mcp, "mount_path", "/agent-gateway")

    body = (await client.get("/api/v1/mcp/info")).json()
    assert body["auth_enabled"] is True
    assert body["mount_path"] == "/agent-gateway"


# ---------------------------------------------------------------------------
# /mcp/calls — the MCP-scoped audit view
# ---------------------------------------------------------------------------


async def _headers_for(db: AsyncSession, *, codes: list[str], username: str) -> dict[str, str]:
    """A user whose role holds exactly ``codes``, issued a working token."""
    role = Role(code=f"role-{username}", name="Limited", is_system=False)
    db.add(role)
    await db.flush()
    for code in codes:
        db.add(RolePermission(role_id=role.id, permission_code=code))
    user = User(
        username=username,
        password_hash=hash_password("irrelevant"),
        display_name="Limited User",
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    token = await issue_web_token(db, user_id=user.id)
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _seed_rows(db: AsyncSession) -> None:
    """Two MCP-namespace rows and one identity row to filter against."""
    await write_audit(
        db,
        event="mcp.tools.call",
        target="echo",
        ok=True,
        detail={"agent_type": "claude-code", "agent_id": "inst-1"},
    )
    await write_audit(db, event="mcp.auth.reject", target="gate", ok=False, error="missing_token")
    await write_audit(db, event="auth.login", username="admin", target="admin", ok=True)
    await db.commit()


async def test_calls_requires_agents_read_not_audit_read(client, db):
    """The two directions of the permission separation:

    - audit:read alone → 403 (the identity trail does not unlock agent
      activity), and
    - mcp:agents:read alone → 200, seeing ONLY mcp.% rows.
    """
    await _seed_rows(db)

    audit_only = await _headers_for(db, codes=["audit:read"], username="auditor")
    resp = await client.get("/api/v1/mcp/calls", headers=audit_only)
    assert resp.status_code == 403

    agents_only = await _headers_for(db, codes=["mcp:agents:read"], username="watcher")
    resp = await client.get("/api/v1/mcp/calls", headers=agents_only)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {row["event"] for row in body["items"]} == {"mcp.tools.call", "mcp.auth.reject"}


async def test_calls_anonymous_401_and_admin_reads_newest_first(client, db, admin_headers):
    """No token at all -> 401 ("who are you"); a token lacking the code
    -> 403 (the previous test). Admin sees everything, newest first."""
    await _seed_rows(db)

    assert (await client.get("/api/v1/mcp/calls")).status_code == 401

    body = (await client.get("/api/v1/mcp/calls", headers=admin_headers)).json()
    # Newest first: the reject row was written after the tool call.
    assert [row["event"] for row in body["items"]] == ["mcp.auth.reject", "mcp.tools.call"]
    call_row: dict[str, Any] = body["items"][1]
    assert call_row["detail"]["agent_type"] == "claude-code"
    assert call_row["target"] == "echo"


async def test_calls_pagination_and_shape(client, db, admin_headers):
    await _seed_rows(db)

    first = (await client.get("/api/v1/mcp/calls?limit=1", headers=admin_headers)).json()
    assert len(first["items"]) == 1 and first["total"] == 2

    second = (await client.get("/api/v1/mcp/calls?limit=1&offset=1", headers=admin_headers)).json()
    assert second["items"][0]["event"] == "mcp.tools.call"
    assert second["items"][0]["id"] != first["items"][0]["id"]

    # Out-of-range params are rejected by FastAPI validation, not clamped.
    assert (await client.get("/api/v1/mcp/calls?limit=0", headers=admin_headers)).status_code == 422
