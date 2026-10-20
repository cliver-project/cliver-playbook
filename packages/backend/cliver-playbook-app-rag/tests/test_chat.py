"""Chat endpoint: retriever -> reranker -> LLM composition.

The test settings pin the offline-safe stages (bm25-only retriever,
noop reranker, stub LLM), so the whole chain runs without model
downloads. The score-floor behaviour is exercised separately with a
stub reranker that claims relevance scores.
"""

from __future__ import annotations

import io

from httpx import AsyncClient

CHAT = "/api/v1/rag/chat"
DOCUMENTS = "/api/v1/rag/documents"


async def _upload_and_index(client: AsyncClient, content: bytes) -> str:
    files = {"file": ("chat.txt", io.BytesIO(content), "text/plain")}
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


async def test_chat_with_no_hits_returns_a_grounded_refusal(client: AsyncClient) -> None:
    r = await client.post(CHAT, json={"question": "anything at all"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "could not find" in body["answer"].lower()
    assert body["citations"] == []
    assert body["no_hits"] is True
    assert body["hits_used"] == 0
    assert body["model_id"] == "stub@1.0"


async def test_chat_with_hits_answers_from_context(client: AsyncClient) -> None:
    await _upload_and_index(client, b"The quick brown fox jumps over the lazy dog. " * 5)

    r = await client.post(CHAT, json={"question": "what does the document say about a fox?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["no_hits"] is False
    assert body["hits_used"] >= 1
    assert "quick" in body["answer"] or "fox" in body["answer"]
    assert len(body["citations"]) == body["hits_used"]
    citation = body["citations"][0]
    assert citation["chunk_id"]
    assert citation["document_id"]
    assert citation["text_preview"]
    assert citation["score"] > 0
    assert body["retriever"] == "bm25-only"
    assert body["reranker"] == "noop"
    assert body["llm"] == "stub"


async def test_chat_respects_rerank_top_k(client: AsyncClient) -> None:
    await _upload_and_index(
        client,
        b"The quick fox runs. " * 20 + b"The quick fox rests. " * 20,
    )

    r = await client.post(CHAT, json={"question": "quick fox", "rerank_top_k": 1})
    assert r.status_code == 200, r.text
    assert r.json()["hits_used"] == 1


async def test_chat_unknown_stage_returns_422(client: AsyncClient) -> None:
    for field in ("retriever", "embedder", "reranker", "llm"):
        r = await client.post(CHAT, json={"question": "x", field: "does-not-exist"})
        assert r.status_code == 422, (field, r.text)
        assert "unknown" in r.json()["detail"]


async def test_chat_rejects_a_mode_the_retriever_cannot_run(client: AsyncClient) -> None:
    r = await client.post(CHAT, json={"question": "x", "mode": "dense"})
    assert r.status_code == 422
    assert "does not support mode" in r.json()["detail"]


async def test_chat_reports_the_effective_mode(client: AsyncClient) -> None:
    r = await client.post(CHAT, json={"question": "anything", "mode": "hybrid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested_mode"] == "hybrid"
    assert body["mode"] == "sparse"


async def test_chat_pipeline_failure_is_a_stable_500(client: AsyncClient, monkeypatch) -> None:
    from cliver_playbook.app.rag.retrieval.bm25_only import Bm25OnlyRetriever

    async def _boom(self, query, *, db):
        raise RuntimeError("retrieval exploded")

    monkeypatch.setattr(Bm25OnlyRetriever, "retrieve", _boom)

    r = await client.post(CHAT, json={"question": "anything"})
    assert r.status_code == 500
    assert r.json()["detail"] == "chat failed"


async def test_chat_requires_permission(raw_client: AsyncClient) -> None:
    r = await raw_client.post(CHAT, json={"question": "anything"})
    assert r.status_code == 401
