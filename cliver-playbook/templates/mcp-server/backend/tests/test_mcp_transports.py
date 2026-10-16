"""Real transports — real server subprocess, real SDK client, real pipes.

Both shapes are exercised end to end, nothing in-process:

- **streamable-http**: a uvicorn subprocess serving the full app (one
  with auth OFF, one with ``CLIVER_MCP__AUTH_ENABLED=true``), driven by
  the SDK's ``streamable_http_client`` over a real TCP port. Auth-wide
  cases (401 header, valid-token session) go through the real gate.
- **stdio**: ``python -m app.mcp --transport stdio`` spawned as a real
  subprocess by ``stdio_client``, JSON-RPC over the actual pipes; the
  fail-fast auth policy is asserted on process exit codes + stderr.

Subprocesses are the point, not an implementation detail: the lifespan
session manager, the asyncpg loop affinity and the alembic interplay
only exist for real when a real process boots. The servers are
module-scoped (one boot per transport per mode); tests within a module
share them and seed their own database state per test.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from sqlalchemy import select

from app.models.entities import AuditLog

_BACKEND_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# subprocess machinery
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _read_log(log: Any) -> str:
    log.seek(0)
    return log.read().decode("utf-8", "replace")


def _wait_for_port(port: int, proc: subprocess.Popen, log: Any, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"server exited early (rc={proc.returncode}):\n{_read_log(log)}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"server on :{port} never became ready:\n{_read_log(log)}")


@pytest.fixture(scope="module")
def http_off_server():
    """Full app on a real port, mcp.auth_enabled=false (template default)."""
    yield from _serve_app(auth_enabled=False)


@pytest.fixture(scope="module")
def http_on_server():
    """Full app on a real port, mcp.auth_enabled=true."""
    yield from _serve_app(auth_enabled=True)


def _serve_app(*, auth_enabled: bool):
    port = _free_port()
    env = {
        **os.environ,
        "CLIVER_MCP__AUTH_ENABLED": "true" if auth_enabled else "false",
    }
    # Log output goes to an anonymous temp file: it must not fill a pipe
    # buffer (deadlocking the server), and it is only read back to make
    # a boot failure diagnosable.
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=_BACKEND_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_port(port, proc, log)
            yield f"http://127.0.0.1:{port}"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


@asynccontextmanager
async def _http_session(base_url: str, headers: dict[str, str]):
    """Initialized SDK client session against a real server."""
    async with (
        create_mcp_http_client(headers=headers) as http_client,
        streamable_http_client(base_url + "/mcp", http_client=http_client) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        yield session, init


def _tool_payload(result: Any) -> dict[str, Any]:
    return json.loads(result.content[0].text)


async def _latest_audit(db: Any, target: str) -> AuditLog:
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
    assert rows, f"expected an audit row for {target!r}"
    return rows[-1]


# ---------------------------------------------------------------------------
# streamable-http — auth OFF
# ---------------------------------------------------------------------------


async def test_http_initialize_and_tools_list(http_off_server):
    async with _http_session(http_off_server, {}) as (session, init):
        assert init.server_info.name == "cliver-app-mcp"
        tools = {t.name for t in (await session.list_tools()).tools}
        assert {"echo", "user_directory"} <= tools


async def test_http_echo_reports_agent_headers_and_audits(http_off_server, db):
    """The identity headers travel the wire into the audit row — the
    header→bind→audit chain works over real HTTP, not just in-process."""
    headers = {"X-MCP-Agent-Type": "claude-code", "X-MCP-Agent-Id": "wire-1"}
    async with _http_session(http_off_server, headers) as (session, _):
        result = await session.call_tool("echo", {"message": "over-http"})
        assert result.is_error is False
        body = _tool_payload(result)
        assert body["message"] == "over-http"
        assert body["user"] is None
        assert body["agent"] == {"type": "claude-code", "id": "wire-1"}
        assert body["transport"] == "http"

    row = await _latest_audit(db, "echo")
    assert row.ok is True
    assert row.detail["agent_type"] == "claude-code"


async def test_http_permission_denial_is_error_result(http_off_server, db):
    """A gated tool under auth OFF returns is_error (model-readable), not
    a crashed session — and the denial is audited."""
    async with _http_session(http_off_server, {}) as (session, _):
        result = await session.call_tool("user_directory", {})
        assert result.is_error is True
        assert "Permission denied" in result.content[0].text

        # The session is still alive after the denial.
        again = await session.call_tool("echo", {"message": "still-here"})
        assert again.is_error is False

    row = await _latest_audit(db, "user_directory")
    assert row.ok is False
    assert "Permission denied" in row.error


# ---------------------------------------------------------------------------
# streamable-http — auth ON
# ---------------------------------------------------------------------------


async def test_http_auth_on_missing_token_401_rfc9728(http_on_server):
    """Raw POST (no SDK): the gate answers 401 with the discovery pointer."""
    async with httpx.AsyncClient(base_url=http_on_server) as client:
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_token"
    www = resp.headers.get("www-authenticate", "")
    assert "resource_metadata=" in www and "missing_token" in www


async def test_http_auth_on_valid_token_full_session(http_on_server, db):
    """A Web-issued token drives a full MCP session through the real gate."""
    from app.auth.tokens import issue_web_token
    from tests.helpers import seed_admin

    user_id = await seed_admin(db)
    token = await issue_web_token(db, user_id=user_id)
    await db.commit()

    headers = {"Authorization": f"Bearer {token}", "X-MCP-Agent-Type": "workbuddy"}
    async with _http_session(http_on_server, headers) as (session, _):
        result = await session.call_tool("echo", {})
        assert result.is_error is False
        body = _tool_payload(result)
        assert body["user"] == {"id": user_id, "username": "admin"}

        # And the gated tool works: seeded admin holds mcp:tools:invoke + user:read.
        directory = await session.call_tool("user_directory", {})
        assert directory.is_error is False
        assert _tool_payload(directory)["users"][0]["username"] == "admin"


# ---------------------------------------------------------------------------
# stdio — the real subprocess
# ---------------------------------------------------------------------------


def _stdio_params(**env_overrides: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp", "--transport", "stdio"],
        env={**os.environ, **env_overrides},
        cwd=_BACKEND_DIR,
    )


async def test_stdio_full_session_with_env_identity(db):
    """initialize / tools-list / call over actual pipes; the env agent
    identity lands in both the payload and the audit row (ip=stdio)."""
    params = _stdio_params(MCP_AGENT_TYPE="codex", MCP_AGENT_ID="pipe-1")
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        assert init.server_info.name == "cliver-app-mcp"
        tools = {t.name for t in (await session.list_tools()).tools}
        assert {"echo", "user_directory"} <= tools

        result = await session.call_tool("echo", {"message": "over-pipe"})
        assert result.is_error is False

    body = _tool_payload(result)
    assert body["message"] == "over-pipe"
    assert body["agent"] == {"type": "codex", "id": "pipe-1"}
    assert body["transport"] == "stdio"
    assert body["user"] is None

    row = await _latest_audit(db, "echo")
    assert row.ip == "stdio"
    assert row.detail["agent_type"] == "codex"


async def _run_stdio_expecting_failure(**env_overrides: str) -> tuple[int, bytes, bytes]:
    """Spawn the stdio entry and collect its early exit.

    All ``MCP_*`` variables are scrubbed first, so ambient values from
    the developer's shell can never flip a fail-fast assertion.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("MCP_")}
    env.update(env_overrides)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.mcp",
        "--transport",
        "stdio",
        cwd=_BACKEND_DIR,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    return proc.returncode or 0, stdout, stderr


async def test_stdio_auth_on_without_token_fails_fast():
    """auth ON + no MCP_BEARER_TOKEN: refuse to start — every call would
    be rejected anyway. Nothing may touch stdout (the protocol channel)."""
    code, stdout, stderr = await _run_stdio_expecting_failure(CLIVER_MCP__AUTH_ENABLED="true")
    assert code == 1
    assert b"MCP_BEARER_TOKEN" in stderr
    assert stdout == b""


async def test_stdio_auth_on_invalid_token_fails_fast():
    code, stdout, stderr = await _run_stdio_expecting_failure(
        CLIVER_MCP__AUTH_ENABLED="true", MCP_BEARER_TOKEN="not-a-real-token"
    )
    assert code == 1
    assert b"unknown, expired or revoked" in stderr
    assert stdout == b""


async def test_stdio_auth_on_must_change_password_fails_fast(db):
    """The HTTP gate answers 403 for this state; the stdio translation is
    refusing to start (there is no per-request check mid-stream)."""
    from app.auth.passwords import hash_password
    from app.auth.tokens import issue_web_token
    from app.models.entities import User

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

    code, stdout, stderr = await _run_stdio_expecting_failure(
        CLIVER_MCP__AUTH_ENABLED="true", MCP_BEARER_TOKEN=token
    )
    assert code == 1
    assert b"change their password" in stderr
    assert stdout == b""
