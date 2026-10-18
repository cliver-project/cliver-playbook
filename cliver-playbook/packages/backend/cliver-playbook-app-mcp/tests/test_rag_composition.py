"""The RAG package inside the composed application, on real PostgreSQL.

Unlike the rag package's own HTTP tests (SQLite plus the lexical
fallback), these tests run the production path: the rag migration is
applied to the temp database by the conftest, documents are stored in
pgvector columns, and search exercises the real dense and tsvector SQL.
The fixture app.yaml pins the stub embedder so the dense leg is
deterministic and no model weights are downloaded.

The audit assertion is deliberate: the RAG audit wrapper is
best-effort and swallows write failures, and a keyword-argument bug in
that wrapper stayed invisible in SQLite tests (no audit table). Against
the migrated schema the row must actually be there.
"""

from __future__ import annotations

import io
import json
from typing import Any

from fastapi.routing import iter_route_contexts
from httpx import AsyncClient
from sqlalchemy import text


async def _upload_and_index(client: AsyncClient, headers: dict[str, str], content: bytes) -> str:
    files = {"file": ("knowledge.txt", io.BytesIO(content), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "128", "chunk_overlap": "0"}
    uploaded = await client.post(
        "/api/v1/rag/documents/upload", files=files, data=data, headers=headers
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]
    indexed = await client.post(f"/api/v1/rag/documents/{document_id}/index", headers=headers)
    assert indexed.status_code == 200, indexed.text
    return document_id


def test_rag_routes_are_in_the_flat_route_table(app) -> None:
    """Composition is one include_router loop; no mount hides a subtree.

    Routes are read through ``iter_route_contexts``: FastAPI 0.143 stores
    included routers lazily as ``_IncludedRouter`` placeholders in
    ``app.routes``, and only this helper expands them with their prefixes.
    """
    paths = {rc.path for rc in iter_route_contexts(app.router.routes)}
    assert "/api/v1/rag/documents/upload" in paths
    assert "/api/v1/rag/search" in paths
    assert "/api/v1/rag/chat" in paths
    assert "/api/v1/rag/stages" in paths


async def test_stage_catalog_serves_every_registry(client: AsyncClient, admin_headers) -> None:
    response = await client.get("/api/v1/rag/stages", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"bm25-only", "pgvector-hybrid"} <= {o["name"] for o in body["retrievers"]}
    assert {"noop", "bge-reranker-v2-m3"} <= {o["name"] for o in body["rerankers"]}
    # Values pinned by the test fixture's rag block.
    assert body["defaults"]["embedder"] == "stub"
    assert body["defaults"]["retriever"] == "pgvector-hybrid"


async def test_search_runs_both_legs_on_postgres(
    client: AsyncClient, admin_headers, db: Any
) -> None:
    headers = {
        **admin_headers,
        "x-forwarded-for": "203.0.113.9",
        "user-agent": "rag-composition-test",
    }
    await _upload_and_index(
        client,
        headers,
        b"The quick brown fox jumps over the lazy dog. " * 20,
    )

    dense = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "dense", "top_k": 5},
        headers=headers,
    )
    assert dense.status_code == 200, dense.text
    assert dense.json()["hits"], "the dense leg returned no rows from the migrated schema"

    sparse = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "sparse", "top_k": 5},
        headers=headers,
    )
    assert sparse.status_code == 200, sparse.text
    assert sparse.json()["hits"], "the tsvector leg returned no rows"

    hybrid = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "hybrid", "top_k": 5},
        headers=headers,
    )
    assert hybrid.status_code == 200, hybrid.text
    assert hybrid.json()["hits"], "RRF fusion dropped both legs' results"

    rows = (
        await db.execute(
            text(
                "SELECT user_id, username, ip, user_agent, ok "
                "FROM audit_logs WHERE event = 'rag.search.run' ORDER BY id"
            )
        )
    ).all()
    assert rows, "the rag audit wrapper failed to write on the migrated schema"
    # Every row is attributed: an audit entry without a user cannot
    # answer "who searched what", and the IP/UA come from the Request.
    for user_id, username, ip, user_agent, ok in rows:
        assert user_id is not None
        assert username == "admin"
        assert ip == "203.0.113.9"
        assert user_agent == "rag-composition-test"
        assert ok is True

    # Upload and index rows are attributed the same way.
    doc_rows = (
        await db.execute(
            text(
                "SELECT user_id, username FROM audit_logs "
                "WHERE event IN ('rag.document.upload', 'rag.document.index') "
                "AND ok IS TRUE"
            )
        )
    ).all()
    assert doc_rows
    for user_id, username in doc_rows:
        assert user_id is not None
        assert username == "admin"


async def test_pending_documents_are_not_searchable(client: AsyncClient, admin_headers) -> None:
    """Upload stores chunks for the preview; only indexing makes them live."""
    files = {"file": ("pending.txt", io.BytesIO(b"quarantineword only. " * 20), "text/plain")}
    data = {
        "chunker": "recursive",
        "embedder": "stub",
        "chunk_size": "128",
        "chunk_overlap": "0",
    }
    uploaded = await client.post(
        "/api/v1/rag/documents/upload", files=files, data=data, headers=admin_headers
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["status"] == "pending"

    for mode in ("sparse", "dense", "hybrid"):
        response = await client.post(
            "/api/v1/rag/search",
            json={"query": "quarantineword", "mode": mode, "top_k": 5},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["hits"] == [], f"pending chunks leaked into {mode} results"


async def test_chat_refusal_is_audited_as_a_successful_run(
    client: AsyncClient, admin_headers, db: Any
) -> None:
    """Finding nothing is a completed request, not a failure."""
    response = await client.post(
        "/api/v1/rag/chat",
        json={"question": "term-that-matches-nothing"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["no_hits"] is True

    row = (
        await db.execute(
            text(
                "SELECT ok, detail FROM audit_logs "
                "WHERE event = 'rag.chat.run' ORDER BY id DESC LIMIT 1"
            )
        )
    ).one()
    ok, detail = row
    assert ok is True
    if isinstance(detail, str):
        detail = json.loads(detail)
    assert detail["no_hits"] is True
    assert detail["args"]["effective_mode"] == "hybrid"


class _ConstantEmbedder:
    """Deterministic 1024-d embedder: one fixed unit direction."""

    def __init__(self, ident: str, hot_index: int) -> None:
        self.id = ident
        self.dim = 1024
        self.max_input_tokens = 8192
        self.supports_query_document_modes = False
        self._hot_index = hot_index

    def embed(self, texts, *, mode="document"):
        vector = [0.0] * self.dim
        vector[self._hot_index] = 1.0
        return [list(vector) for _ in texts]

    def estimate_tokens(self, text: str) -> int:
        return len(text.split())


def _register_two_1024_embedders() -> None:
    from cliver_playbook.app.rag.embedding.registry import names, register

    for name, hot_index in (("test-1024-a", 0), ("test-1024-b", 1)):
        if name not in names():
            register(name, lambda n=name, i=hot_index: _ConstantEmbedder(f"{n}@1.0", i))


async def test_dense_leg_uses_the_1024_index_path_and_embedder_identity(
    client: AsyncClient, admin_headers
) -> None:
    """The production dimension and the embedder-identity predicate.

    ``test-1024-a`` and ``test-1024-b`` have the same dimension but
    different ids and different vector spaces. A dense query embedded
    with B must not match rows embedded with A: comparing same-width
    vectors from different models is exactly the silent-garbage case the
    identity filter exists to prevent.
    """
    _register_two_1024_embedders()
    files = {"file": ("wide.txt", io.BytesIO(b"The quick brown fox. " * 20), "text/plain")}
    data = {
        "chunker": "recursive",
        "embedder": "test-1024-a",
        "chunk_size": "128",
        "chunk_overlap": "0",
    }
    uploaded = await client.post(
        "/api/v1/rag/documents/upload", files=files, data=data, headers=admin_headers
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]
    indexed = await client.post(f"/api/v1/rag/documents/{document_id}/index", headers=admin_headers)
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["dim"] == 1024
    assert indexed.json()["embedder_version"] == "test-1024-a@1.0"

    matching = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "dense", "embedder": "test-1024-a"},
        headers=admin_headers,
    )
    assert matching.status_code == 200, matching.text
    assert matching.json()["hits"], "the 1024-d dense path returned no rows"

    other = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "dense", "embedder": "test-1024-b"},
        headers=admin_headers,
    )
    assert other.status_code == 200, other.text
    assert other.json()["hits"] == [], "vectors from a different embedder must not match"


async def test_query_embedder_override_drives_the_dense_leg(
    client: AsyncClient, admin_headers, monkeypatch
) -> None:
    """Search must let the caller name the embedder that indexed the rows.

    The upload endpoint accepts any registered embedder per document, so
    the query side needs the same choice: with a different process
    default (here a name no registry knows, which would raise inside the
    dense leg) the explicit override must still win and match the
    stub-indexed rows.
    """
    from cliver_playbook.app.rag.settings import settings as rag_settings

    await _upload_and_index(
        client,
        admin_headers,
        b"The quick brown fox jumps over the lazy dog. " * 20,
    )
    monkeypatch.setattr(rag_settings.rag, "embedder", "missing-default")

    response = await client.post(
        "/api/v1/rag/search",
        json={
            "query": "quick brown fox",
            "mode": "dense",
            "top_k": 5,
            "embedder": "stub",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["hits"], "the dense leg ignored the per-call embedder override"


async def test_chat_answers_from_retrieved_context(client: AsyncClient, admin_headers) -> None:
    await _upload_and_index(
        client,
        admin_headers,
        b"The quick brown fox jumps over the lazy dog. " * 20,
    )

    response = await client.post(
        "/api/v1/rag/chat",
        json={"question": "what does the document say about foxes?"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["no_hits"] is False
    assert body["citations"]
    assert "fox" in body["answer"].lower()
    assert body["retriever"] == "pgvector-hybrid"
    assert body["reranker"] == "noop"
    assert body["llm"] == "stub"


async def test_rag_routes_are_gated_without_a_token(client: AsyncClient) -> None:
    """The composed app keeps the RAG permission gate: registration must
    not accidentally publish an anonymous surface."""
    response = await client.get("/api/v1/rag/stages")
    assert response.status_code == 401
