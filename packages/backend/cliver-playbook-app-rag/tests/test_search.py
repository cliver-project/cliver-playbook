"""Search endpoint behaviour.

These tests run against the lexical retriever (the test settings pin
``rag.retriever`` to ``bm25-only``) so the HTTP contract is verified on
SQLite; the pgvector-hybrid SQL is covered by the live smoke run.
"""

from __future__ import annotations

import io

from httpx import AsyncClient

SEARCH = "/api/v1/rag/search"
DOCUMENTS = "/api/v1/rag/documents"


async def _upload_and_index(client: AsyncClient, content: bytes) -> str:
    files = {"file": ("search.txt", io.BytesIO(content), "text/plain")}
    data = {
        "chunker": "recursive",
        "embedder": "stub",
        "chunk_size": "128",
        "chunk_overlap": "0",
    }
    r = await client.post(f"{DOCUMENTS}/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    document_id = r.json()["document_id"]
    r2 = await client.post(f"{DOCUMENTS}/{document_id}/index")
    assert r2.status_code == 200, r2.text
    return document_id


async def test_search_on_empty_index_returns_no_hits(client: AsyncClient) -> None:
    r = await client.post(SEARCH, json={"query": "anything at all"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hits"] == []
    assert body["retriever"] == "bm25-only"


async def test_search_returns_matching_indexed_chunk(client: AsyncClient) -> None:
    await _upload_and_index(
        client,
        b"The quick brown fox jumps over the lazy dog. A slow turtle crosses the road.",
    )

    r = await client.post(SEARCH, json={"query": "quick fox"})
    assert r.status_code == 200, r.text
    hits = r.json()["hits"]
    assert hits
    assert "quick brown fox" in hits[0]["text"]
    assert hits[0]["score"] > 0
    assert hits[0]["chunk_id"]
    assert hits[0]["document_id"]


async def test_search_mode_is_echoed_and_respected(client: AsyncClient) -> None:
    await _upload_and_index(client, b"The quick brown fox.")

    r = await client.post(SEARCH, json={"query": "quick", "mode": "sparse"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "sparse"
    assert body["requested_mode"] == "sparse"


async def test_search_reports_the_effective_mode_after_degradation(
    client: AsyncClient,
) -> None:
    """bm25-only has no dense leg: a hybrid request runs sparse and says so.

    Echoing the requested mode would let the UI compare a "hybrid" run
    that was in fact lexical-only, which is exactly the mislabelling the
    stage comparison exists to avoid.
    """
    await _upload_and_index(client, b"The quick brown fox.")

    r = await client.post(SEARCH, json={"query": "quick", "mode": "hybrid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested_mode"] == "hybrid"
    assert body["mode"] == "sparse"


async def test_search_rejects_a_mode_the_retriever_cannot_run(
    client: AsyncClient,
) -> None:
    # bm25-only declares no dense capability; a dense request must be a
    # client error rather than a silent fallback to lexical hits.
    r = await client.post(SEARCH, json={"query": "quick", "mode": "dense"})
    assert r.status_code == 422
    assert "does not support mode" in r.json()["detail"]


async def test_search_retrieval_failure_is_a_stable_500(client: AsyncClient, monkeypatch) -> None:
    from cliver_playbook.app.rag.retrieval.bm25_only import Bm25OnlyRetriever

    async def _boom(self, query, *, db):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(Bm25OnlyRetriever, "retrieve", _boom)

    r = await client.post(SEARCH, json={"query": "anything"})
    assert r.status_code == 500
    assert r.json()["detail"] == "retrieval failed"


async def test_search_top_k_limits_hits(client: AsyncClient) -> None:
    # Enough distinct sentences that the lexical leg can score several
    # chunks; the recursive chunker splits on the small chunk_size.
    await _upload_and_index(
        client,
        b"The quick fox runs. " * 20 + b"The quick fox rests. " * 20,
    )

    r = await client.post(SEARCH, json={"query": "quick fox", "top_k": 1})
    assert r.status_code == 200, r.text
    assert len(r.json()["hits"]) == 1


async def test_search_unknown_retriever_returns_422(client: AsyncClient) -> None:
    r = await client.post(SEARCH, json={"query": "x", "retriever": "does-not-exist"})
    assert r.status_code == 422
    assert "unknown retriever" in r.json()["detail"]


async def test_search_unknown_embedder_returns_422(client: AsyncClient) -> None:
    """The query embedder is a per-call choice; an unregistered name is a
    client error and must be rejected before retrieval starts."""
    r = await client.post(SEARCH, json={"query": "x", "embedder": "does-not-exist"})
    assert r.status_code == 422
    assert "unknown embedder" in r.json()["detail"]


async def test_search_rejects_empty_query(client: AsyncClient) -> None:
    r = await client.post(SEARCH, json={"query": ""})
    assert r.status_code == 422


async def test_search_requires_permission(raw_client: AsyncClient) -> None:
    r = await raw_client.post(SEARCH, json={"query": "anything"})
    assert r.status_code == 401
