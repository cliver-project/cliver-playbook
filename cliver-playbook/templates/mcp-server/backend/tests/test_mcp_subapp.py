"""M2: the MCP sub-application is live inside the parent FastAPI app.

These tests boot the *real* application object through Starlette's
TestClient, whose context manager runs the parent lifespan — which in
turn enters the sub-app's lifespan and boots the streamable-http
session manager. An ``initialize`` request that answers with real
serverInfo proves the whole chain: route match at ``/mcp`` (exact, no
redirect), session manager running, SDK server responding.

Lifecycle note: the SDK's StreamableHTTPSessionManager allows exactly
one ``run()`` per instance ("create a new instance if you need to run
again" — one lifespan per process, which is exactly how production
serves it). The booted client is therefore **module-scoped**: every
test in this file shares the one running session manager instead of
each test trying to boot its own.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from app.main import app

# A minimal but valid JSON-RPC initialize request. protocolVersion matches
# the SDK's latest (2026-07-28); capabilities can be empty for initialize.
INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2026-07-28",
        "capabilities": {},
        "clientInfo": {"name": "mcp-structural-test", "version": "0.0.0"},
    },
}

MCP_ACCEPT = "application/json, text/event-stream"


@pytest.fixture(scope="module")
def booted_client() -> Iterator[TestClient]:
    """One entered TestClient for the whole module (see module docstring)."""
    with TestClient(app) as client:
        yield client


def test_build_mcp_subapp_is_singleton():
    """The sub-app is built exactly once per process: the SDK registers its
    session manager on the server singleton as a build side-effect, so a
    second build would orphan the first app's manager."""
    from app.mcp import subapp as mod
    from app.mcp.subapp import build_mcp_subapp

    assert build_mcp_subapp() is mod._subapp
    assert build_mcp_subapp() is build_mcp_subapp()


def test_initialize_answers_over_streamable_http(booted_client: TestClient):
    """POST /mcp with an initialize request returns the server's identity —
    the endpoint, the session manager and the lifespan composition all work."""
    resp = booted_client.post(
        "/mcp",
        json=INITIALIZE_PAYLOAD,
        headers={"Accept": MCP_ACCEPT},
    )
    assert resp.status_code == 200
    assert "cliver-app-mcp" in resp.text


def test_root_mount_does_not_shadow_api_routes(booted_client: TestClient):
    """The sub-app is mounted at "/" AFTER everything else; Starlette matches
    in order, so API / OAuth / docs routes keep their precedence.

    Asserted structurally (the mount is the router's LAST entry — recent
    FastAPI wraps included routers in _IncludedRouter objects without a
    path attribute, so counting API routes by prefix no longer works)
    plus a behavioural DB-free request. /health is deliberately NOT used
    here: the TestClient portal runs on its own event loop while the
    autouse DB-reset fixture runs on pytest-asyncio's per-test loops, and
    sharing the asyncpg pool across them trips loop-affinity errors that
    say nothing about routing.
    """
    from starlette.routing import Mount

    from app.mcp.subapp import build_mcp_subapp

    last = app.router.routes[-1]
    assert isinstance(last, Mount) and last.app is build_mcp_subapp(), (
        "the '/' mount must be the final route — anything declared after it would be shadowed"
    )

    assert booted_client.get("/api/v1/version").status_code == 200
    assert booted_client.get("/api/v1/definitely-not-a-route").status_code == 404


def test_initialize_rejects_non_json_content_type(booted_client: TestClient):
    """The transport enforces Content-Type on POST (kept even with DNS
    rebinding protection off) — a form post must not reach the protocol."""
    resp = booted_client.post(
        "/mcp",
        content=b"jsonrpc=2.0",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": MCP_ACCEPT,
        },
    )
    assert resp.status_code == 400


def test_unmounted_paths_fall_through_to_404(booted_client: TestClient):
    """Paths the sub-app does not own still 404 at the parent level —
    the MCP surface adds no catch-all behaviour beyond its own route."""
    assert booted_client.get("/nope").status_code == 404
