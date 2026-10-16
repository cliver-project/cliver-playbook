"""M1 structural tests for the MCP module skeleton.

The skeleton ships with no behavior yet — these tests are about the
*shape* being right: the catalog registers without breaking UM, the
viewer/agent accessors behave correctly under a no-gate scenario,
the audit wrapper writes rows that match the audit_logs contract, and
the gate middleware refuses to run (M3 will replace this with real
behavior). The point is to lock down the surface so M2/M3 can grow
into it without backtracking.
"""

from __future__ import annotations

import asyncio

import pytest

from app.auth.permissions import PERMISSION_CODES

# ---------------------------------------------------------------------------
# permissions catalog (statically extended — see app/mcp/permissions.py)
# ---------------------------------------------------------------------------


def test_mcp_codes_present_in_global_catalog():
    """The four mcp:* codes are part of PERMISSION_CODES at import time —
    require_perm's by-value import means runtime patching could never work."""
    from app.mcp.permissions import MCP_PERMISSION_CODES

    for code in MCP_PERMISSION_CODES:
        assert code in PERMISSION_CODES, f"missing MCP code: {code}"


def test_catalog_dump_includes_mcp_group():
    """The admin permissions endpoint dump exposes the MCP group."""
    from app.auth.permissions import catalog_as_dicts

    rows = catalog_as_dicts()
    mcp_rows = [r for r in rows if r["group"] == "MCP"]
    assert {r["code"] for r in mcp_rows} == {
        "mcp:tools:invoke",
        "mcp:prompts:get",
        "mcp:resources:read",
        "mcp:agents:read",
    }


# ---------------------------------------------------------------------------
# context accessors
# ---------------------------------------------------------------------------


def test_current_viewer_raises_when_unbound():
    """A tool that reads current_viewer() outside any request gets RuntimeError,
    not a silent AnonymousViewer — silent defaults hide gate misconfiguration."""
    from app.mcp.context import current_viewer

    with pytest.raises(RuntimeError, match="No viewer bound"):
        current_viewer()


def test_anonymous_viewer_has_returns_false():
    """AnonymousViewer.has() is always False, so a perm-required tool
    rejects an auth-OFF caller even when the gate is bypassed."""
    from app.mcp.context import AnonymousViewer

    v = AnonymousViewer()
    assert v.has("mcp:tools:invoke") is False
    assert v.has("user:read") is False
    assert v.permissions == frozenset()
    assert v.user_id is None


def test_agent_identity_normalised_type_unknown_when_empty():
    """An empty / missing agent_type lands on 'unknown' so the audit row
    never carries an empty string in that column."""
    from app.mcp.context import AgentIdentity

    a = AgentIdentity()
    assert a.normalised_type() == "unknown"
    assert AgentIdentity(agent_type="").normalised_type() == "unknown"
    assert AgentIdentity(agent_type="Claude-Code").normalised_type() == "claude-code"


def test_agent_identity_whitelist_enforced():
    """A type not in the configured whitelist normalises to 'unknown'."""
    from app.mcp.context import AgentIdentity

    a = AgentIdentity(agent_type="rogue")
    assert a.normalised_type(whitelist={"claude-code", "workbuddy"}) == "unknown"
    assert a.normalised_type(whitelist={"claude-code", "workbuddy", "rogue"}) == "rogue"


def test_agent_identity_truncated_id():
    from app.mcp.context import AgentIdentity

    a = AgentIdentity(agent_id="x" * 500)
    assert len(a.truncated_id(128)) == 128


# ---------------------------------------------------------------------------
# audit wrapper contract
# ---------------------------------------------------------------------------


async def test_audit_wrapper_writes_one_row(db):
    """write_tool_audit produces exactly one audit_logs row with the MCP
    event name and the agent_* fields populated."""
    from sqlalchemy import select

    from app.mcp.audit import write_tool_audit
    from app.mcp.context import AgentIdentity, bind_agent, bind_request, bind_viewer
    from app.models.entities import AuditLog

    bind_viewer(None)  # anonymous: user_id=None is the documented case
    bind_agent(AgentIdentity(agent_type="claude-code", agent_id="inst-1"))
    bind_request({"type": "http", "client": ("127.0.0.1", 12345), "headers": []})

    await write_tool_audit(
        method="tools/call",
        target="echo",
        args={"message": "hi"},
        ok=True,
        duration_ms=12,
    )

    rows = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "mcp.tools.call")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.target == "echo"
    assert row.ok is True
    assert row.detail["args"] == {"message": "hi"}
    assert row.detail["duration_ms"] == 12
    assert row.detail["agent_type"] == "claude-code"
    assert row.detail["agent_id"] == "inst-1"
    assert row.user_id is None


async def test_audit_wrapper_records_failure(db):
    """A failed tool call still lands a row, with ok=False and the error string."""
    from sqlalchemy import select

    from app.mcp.audit import write_tool_audit
    from app.mcp.context import AgentIdentity, bind_agent, bind_request, bind_viewer
    from app.models.entities import AuditLog

    bind_viewer(None)
    bind_agent(AgentIdentity())
    bind_request({"type": "stdio"})

    await write_tool_audit(
        method="tools/call",
        target="boom",
        ok=False,
        error="kaboom",
    )
    row = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "mcp.tools.call")))
        .scalars()
        .one()
    )
    assert row.ok is False
    assert row.error == "kaboom"
    assert row.ip == "stdio"  # transport tag, not empty
    assert row.detail["agent_type"] == "unknown"


async def test_audit_wrapper_truncates_long_args(db):
    from sqlalchemy import select

    from app.mcp.audit import _MAX_ARG_CHARS, write_tool_audit
    from app.mcp.context import AgentIdentity, bind_agent, bind_request, bind_viewer
    from app.models.entities import AuditLog

    bind_viewer(None)
    bind_agent(AgentIdentity())
    bind_request({"type": "http", "client": ("127.0.0.1", 1), "headers": []})

    huge = "x" * (_MAX_ARG_CHARS * 4)
    await write_tool_audit(method="tools/call", target="echo", args={"blob": huge}, ok=True)

    row = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "mcp.tools.call")))
        .scalars()
        .one()
    )
    assert len(row.detail["args"]["blob"]) == _MAX_ARG_CHARS


async def test_audit_wrapper_swallows_exceptions(caplog):
    """A write_audit that raises is logged + swallowed, not propagated —
    a DB hiccup must not break an otherwise-successful tool call."""
    from app.mcp.audit import write_tool_audit
    from app.mcp.context import AgentIdentity, bind_agent, bind_request, bind_viewer

    bind_viewer(None)
    bind_agent(AgentIdentity())
    bind_request({"type": "http", "client": ("127.0.0.1", 1), "headers": []})

    # Force write_audit to raise by monkey-patching it on the module alias
    # the wrapper imports from.
    import app.mcp.audit as mcp_audit_mod

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated db failure")

    original = mcp_audit_mod.write_audit
    mcp_audit_mod.write_audit = boom  # type: ignore[assignment]
    try:
        with caplog.at_level("WARNING"):
            await write_tool_audit(method="tools/call", target="x", ok=True)
    finally:
        mcp_audit_mod.write_audit = original  # type: ignore[assignment]
    assert any("MCP audit write failed" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# server singleton
# ---------------------------------------------------------------------------


def test_server_singleton_is_an_mcp_instance():
    from mcp.server.mcpserver import MCPServer

    from app.mcp.server import mcp

    assert isinstance(mcp, MCPServer)
    assert mcp.name == "cliver-app-mcp"


# ---------------------------------------------------------------------------
# gate middleware stub raises (M3 will fill in)
# ---------------------------------------------------------------------------


def test_gate_middleware_call_raises_not_implemented():
    """M1 stub: the gate refuses to run. M3 will replace the body."""

    from app.mcp.auth import MCPGateMiddleware

    async def _inner(scope, receive, send):
        return None

    gate = MCPGateMiddleware(_inner)
    with pytest.raises(NotImplementedError, match="M3"):
        asyncio.run(gate.__call__({}, None, None))


# ---------------------------------------------------------------------------
# auth gate path is NOT yet wired (subapp still returns None at M1)
# ---------------------------------------------------------------------------


def test_subapp_returns_none_at_m1():
    """build_mcp_subapp() is a no-op at M1; the parent's mount is skipped."""
    from app.mcp.subapp import build_mcp_subapp

    assert build_mcp_subapp() is None
