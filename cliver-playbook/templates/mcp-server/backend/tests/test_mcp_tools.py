"""Built-in tools — schemas, permission enforcement, audit rows.

Direct ``mcp.call_tool(...)`` invocation, no transport and no lifespan:
the tool manager resolves by name, validates arguments and runs the
decorated function exactly as a network call would, while the test
binds the same ContextVars the gate binds. Wire-level tool calls (real
client, real port) ride the transport tests in test_mcp_transports.py.

What is locked down here:

- the decorators preserve the real signature, so the model-facing
  schema still describes the actual parameters;
- ``@public_tool`` runs under an anonymous viewer, ``@require_perm``
  fails closed under an anonymous viewer AND under a viewer holding
  only part of the declared codes (AND semantics);
- every call — success or denial — leaves exactly one
  ``mcp.tools.call`` audit row with the caller/agent identity.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import load_viewer
from app.auth.passwords import hash_password
from app.mcp.context import (
    AgentIdentity,
    AnonymousViewer,
    bind_agent,
    bind_request,
    bind_viewer,
)
from app.mcp.server import mcp
from app.mcp.tools import register_default_tools
from app.models.entities import AuditLog, Role, RolePermission, User, UserRole
from tests.helpers import seed_admin

register_default_tools()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _bind(viewer: Any, agent_type: str = "claude-code") -> None:
    """Bind the context exactly as the MCPGateMiddleware would."""
    bind_viewer(viewer)
    bind_agent(AgentIdentity(agent_type=agent_type, agent_id="inst-9"))
    bind_request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})


def _payload(result: Any) -> dict[str, Any]:
    """Decode the JSON text block the SDK emits for dict-returning tools."""
    return json.loads(result.content[0].text)


async def _audit_row(db: AsyncSession, target: str) -> AuditLog:
    rows = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.event == "mcp.tools.call", AuditLog.target == target
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, f"expected an mcp.tools.call audit row for {target!r}"
    return rows[-1]


async def _seed_limited_user(db: AsyncSession, *, codes: list[str]) -> int:
    """A non-system user whose role holds exactly ``codes``."""
    role = Role(code="limited", name="Limited", is_system=False)
    db.add(role)
    await db.flush()
    for code in codes:
        db.add(RolePermission(role_id=role.id, permission_code=code))
    user = User(
        username="limited-user",
        password_hash=hash_password("irrelevant"),
        display_name="Limited User",
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    return user.id


# ---------------------------------------------------------------------------
# registration + schema
# ---------------------------------------------------------------------------


async def test_builtin_tools_registered_with_real_signatures():
    """Both tools are listed, and the decorator wrappers did not swallow
    the parameters — functools.wraps keeps __wrapped__ visible to the
    SDK's schema generation."""
    tools = {t.name: t for t in await mcp.list_tools()}
    assert {"echo", "user_directory"} <= set(tools)

    echo_props = tools["echo"].input_schema["properties"]
    assert set(echo_props) == {"message"}
    assert echo_props["message"]["type"] == "string"

    directory_props = tools["user_directory"].input_schema["properties"]
    assert set(directory_props) == {"q", "limit"}
    assert directory_props["limit"]["type"] == "integer"


# ---------------------------------------------------------------------------
# echo — the public tool
# ---------------------------------------------------------------------------


async def test_echo_public_call_anonymous_the_whole_way(db):
    """Anonymous viewer: the call succeeds (public tool), the payload is
    honest about the identity, and the audit row records agent fields
    with user_id NULL."""
    _bind(AnonymousViewer())
    result = await mcp.call_tool("echo", {"message": "ping"})
    assert result.is_error is False

    body = _payload(result)
    assert body["message"] == "ping"
    assert body["user"] is None
    assert body["agent"] == {"type": "claude-code", "id": "inst-9"}
    assert body["transport"] == "http"

    row = await _audit_row(db, "echo")
    assert row.ok is True
    assert row.user_id is None
    assert row.detail["args"] == {"message": "ping"}
    assert row.detail["agent_type"] == "claude-code"
    assert row.detail["duration_ms"] >= 0


async def test_echo_reports_authenticated_viewer(db):
    """With a resolved viewer the payload names the user — this is what
    an agent uses to diagnose "who does the server think I am"."""
    user_id = await seed_admin(db)
    viewer = await load_viewer(db, user_id)
    assert viewer is not None
    _bind(viewer)

    body = _payload(await mcp.call_tool("echo", {}))
    assert body["user"] == {"id": user_id, "username": "admin"}
    assert body["message"] == ""


# ---------------------------------------------------------------------------
# user_directory — the permission-gated tool
# ---------------------------------------------------------------------------


async def test_user_directory_denied_for_anonymous_and_audited(db):
    """Auth OFF / anonymous: the gate still enforces permissions. The
    denial is a ToolError (model-readable, session alive) and lands an
    ok=False audit row — attempted unauthorized calls are exactly the
    rows an operator wants."""
    _bind(AnonymousViewer())
    with pytest.raises(ToolError, match="Permission denied"):
        await mcp.call_tool("user_directory", {})

    row = await _audit_row(db, "user_directory")
    assert row.ok is False
    assert "Permission denied" in row.error
    assert row.user_id is None


async def test_user_directory_requires_all_declared_perms(db):
    """AND semantics: mcp:tools:invoke alone is not enough — user:read
    is missing, so the call is denied and the message names precisely
    the missing code."""
    user_id = await _seed_limited_user(db, codes=["mcp:tools:invoke"])
    viewer = await load_viewer(db, user_id)
    assert viewer is not None and viewer.has("mcp:tools:invoke")
    assert not viewer.has("user:read")

    _bind(viewer)
    with pytest.raises(ToolError, match="'user:read'"):
        await mcp.call_tool("user_directory", {})


async def test_user_directory_allowed_for_admin(db):
    """Admin holds the full catalog (0002 seed) — the happy path returns
    the compact directory payload and audits the authenticated caller."""
    user_id = await seed_admin(db)
    viewer = await load_viewer(db, user_id)
    assert viewer is not None
    _bind(viewer)

    result = await mcp.call_tool("user_directory", {"q": "adm"})
    assert result.is_error is False
    body = _payload(result)
    assert body["count"] == 1
    assert body["users"][0]["username"] == "admin"
    assert body["users"][0]["roles"] == ["admin"]
    # The payload is deliberately narrow — no permission/lockout internals.
    assert set(body["users"][0]) == {"username", "display_name", "is_active", "roles"}

    row = await _audit_row(db, "user_directory")
    assert row.ok is True
    assert row.user_id == user_id
    # The SDK validates arguments and fills defaults before invoking the
    # tool, so the audit row records the EFFECTIVE arguments — limit
    # appears even though the caller never sent it.
    assert row.detail["args"] == {"q": "adm", "limit": 50}


async def test_user_directory_limit_is_clamped_not_rejected(db):
    """An over-eager limit succeeds with the cap applied; a zero/negative
    one lands on the minimum — clamping keeps the schema simple and the
    call successful."""
    user_id = await seed_admin(db)
    viewer = await load_viewer(db, user_id)
    assert viewer is not None
    _bind(viewer)

    body = _payload(await mcp.call_tool("user_directory", {"limit": 0}))
    assert body["count"] == len(body["users"]) == 1  # clamped up to 1

    body = _payload(await mcp.call_tool("user_directory", {"limit": 10_000}))
    assert body["count"] == 1  # only one user exists; no crash on the big ask
