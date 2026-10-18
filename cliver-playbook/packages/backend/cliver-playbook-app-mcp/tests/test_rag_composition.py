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
    await _upload_and_index(
        client,
        admin_headers,
        b"The quick brown fox jumps over the lazy dog. " * 20,
    )

    dense = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "dense", "top_k": 5},
        headers=admin_headers,
    )
    assert dense.status_code == 200, dense.text
    assert dense.json()["hits"], "the dense leg returned no rows from the migrated schema"

    sparse = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "sparse", "top_k": 5},
        headers=admin_headers,
    )
    assert sparse.status_code == 200, sparse.text
    assert sparse.json()["hits"], "the tsvector leg returned no rows"

    hybrid = await client.post(
        "/api/v1/rag/search",
        json={"query": "quick brown fox", "mode": "hybrid", "top_k": 5},
        headers=admin_headers,
    )
    assert hybrid.status_code == 200, hybrid.text
    assert hybrid.json()["hits"], "RRF fusion dropped both legs' results"

    rows = (
        (await db.execute(text("SELECT event FROM audit_logs WHERE event = 'rag.search.run'")))
        .scalars()
        .all()
    )
    assert rows, "the rag audit wrapper failed to write on the migrated schema"


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
