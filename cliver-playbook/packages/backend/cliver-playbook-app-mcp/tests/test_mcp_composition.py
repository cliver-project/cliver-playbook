"""The composed application: one flat route table, no mounted sub-applications.

This file is the guard for the architecture decision that replaced the MCP
sub-application mount (ADR-0017). What it pins, and why each part matters:

- **No ``Mount`` in the route table.** Every package contributes its routes
  through ``ROUTERS`` and ``create_app`` includes them in one loop. A mount
  would hide its subtree from the parent's route table (no single source of
  truth, no single prefix policy) and is exactly what this refactor removed.
- **No duplicate ``(path, methods)`` pair.** One deliberate exception exists
  and is asserted as such: the identity package's OAuth 2.1 mount inserts its
  AS-metadata shadow route in front of the SDK's own route at the same path
  (first match wins, both render the same document). That pair comes from
  ``mount_oauth_routes``, not from a package's ``ROUTERS`` list, and it is the
  SDK's patching seam rather than a composition collision.
- **``/mcp`` is a plain route at the fixed path, with no method restriction.**
  The transport answers POST / GET / DELETE itself, so the route must not
  declare methods; and the path must match exactly — a 307 to ``/mcp/`` would
  mean a client that POSTs the URL it was handed gets a redirect instead of a
  JSON-RPC frame (ADR-0017).
- **``/mcp`` stays out of the OpenAPI schema.** It speaks JSON-RPC, not REST:
  publishing a fabricated HTTP contract for it would be worse than publishing
  nothing.
- **The endpoint actually serves.** An ``initialize`` request that answers with
  real ``serverInfo`` proves the whole chain at once: route match through
  ``include_router``, the lifespan having installed the session manager, the
  gate passing the request through, and the SDK server responding.

Lifecycle note: the SDK's ``StreamableHTTPSessionManager`` allows exactly one
``run()`` per instance ("create a new instance if you need to run again" — one
lifespan per process, which is how production serves it). The booted client is
therefore **module-scoped**: every test in this file shares the one running
session manager instead of each test trying to boot its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.routing import RouteContext, iter_route_contexts
from starlette.routing import Mount
from starlette.testclient import TestClient

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.mcp.api.streamable import MCP_PATH, install_streamable_app

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

# The one intentional same-path pair (see module docstring).
_OAUTH_SHADOW_METADATA_PATH = "/.well-known/oauth-authorization-server"


def _discard_pool() -> None:
    """Drop the process engine pool without closing its connections.

    asyncpg connections are bound to the event loop that created them. The
    TestClient runs the lifespan in its own portal loop, while the pool may
    still hold connections acquired in a previous test's (now closed) loop.
    ``close=False`` replaces the pool without touching those connections:
    they belong to loops this fixture must not drive, and closing the
    lifespan would otherwise pick one up across loops and fail startup.
    """
    asyncio.run(runtime.engine().dispose(close=False))


@pytest.fixture(scope="module")
def booted_client(app) -> Iterator[TestClient]:
    """One entered TestClient for the whole process (see module docstring)."""
    _discard_pool()
    with TestClient(app) as client:
        yield client
    _discard_pool()


def _route_table(app) -> list[RouteContext]:
    """The application's effective routes, prefixes already applied."""
    return list(iter_route_contexts(app.router.routes))


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


def test_route_table_has_no_mounts(app):
    """Nothing is mounted: the whole surface is visible in one flat table."""
    mounts = [rc.path for rc in _route_table(app) if isinstance(rc.route, Mount)]
    assert mounts == [], f"mounted sub-applications are not allowed: {mounts}"


def test_route_paths_and_methods_are_unique(app):
    """Including every package's ROUTERS in one loop must not collide.

    A collision is the failure mode a mount used to hide: two packages claiming
    the same (path, methods) would resolve by declaration order, silently
    shadowing one of them.
    """
    pairs = [(rc.path, tuple(sorted(rc.methods or ()))) for rc in _route_table(app)]
    duplicates = {pair for pair in pairs if pairs.count(pair) > 1}
    assert duplicates == {(_OAUTH_SHADOW_METADATA_PATH, ("GET", "HEAD", "OPTIONS"))}, (
        "unexpected duplicate (path, methods) pairs — two packages claim the same route"
    )


def test_protocol_endpoint_is_a_plain_unrestricted_route(app):
    """``/mcp`` is an ordinary route, matches every method, and is exact-match.

    Method-unrestricted on purpose: the transport decides what POST, GET and
    DELETE mean. A concrete ``methods`` list here would turn those SDK answers
    into 405s.
    """
    matching = [rc for rc in _route_table(app) if rc.path == MCP_PATH]
    assert len(matching) == 1
    endpoint = matching[0]
    assert not isinstance(endpoint.route, Mount)
    assert not endpoint.methods, f"{MCP_PATH} must not restrict methods: {endpoint.methods}"


def test_protocol_endpoint_is_absent_from_the_openapi_schema(app):
    """JSON-RPC has no place in a REST schema (and no request model to show)."""
    paths = app.openapi()["paths"]
    assert MCP_PATH not in paths
    assert "/api/v1/mcp/info" in paths  # the REST-ish surface is still published


def test_install_streamable_app_is_idempotent():
    """One session manager per process: the SDK registers it on the server
    singleton as a build side-effect, so a second build would orphan the
    first one's sessions (and its lifespan could never be entered)."""
    first = install_streamable_app()
    assert install_streamable_app() is first


# ---------------------------------------------------------------------------
# behaviour through the real application
# ---------------------------------------------------------------------------


def test_initialize_answers_over_streamable_http(booted_client: TestClient):
    """POST /mcp with an initialize request returns the server's identity —
    route, gate, session manager and lifespan all work together."""
    resp = booted_client.post(
        MCP_PATH,
        json=INITIALIZE_PAYLOAD,
        headers={"Accept": MCP_ACCEPT},
    )
    assert resp.status_code == 200  # a 307 here would mean the path is not exact
    assert "cliver-app-mcp" in resp.text


def test_initialize_rejects_non_json_content_type(booted_client: TestClient):
    """The transport enforces Content-Type on POST (kept even with DNS
    rebinding protection off) — a form post must not reach the protocol."""
    resp = booted_client.post(
        MCP_PATH,
        content=b"jsonrpc=2.0",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": MCP_ACCEPT,
        },
    )
    assert resp.status_code == 400


def test_composed_api_routes_keep_their_precedence(booted_client: TestClient):
    """Composition, not precedence-by-declaration-order: the API surface of
    every package answers, and unknown paths still 404 at the application
    level — the MCP surface adds no catch-all."""
    assert booted_client.get("/api/v1/version").status_code == 200
    assert booted_client.get("/api/v1/mcp/info").status_code == 200
    assert booted_client.get("/nope").status_code == 404
