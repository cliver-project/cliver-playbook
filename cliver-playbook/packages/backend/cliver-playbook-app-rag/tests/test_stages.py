"""Stage-discovery endpoint: the UI's source of selectable stage names."""

from __future__ import annotations

from httpx import AsyncClient

STAGES = "/api/v1/rag/stages"


async def test_stages_lists_every_registry(client: AsyncClient) -> None:
    r = await client.get(STAGES)
    assert r.status_code == 200, r.text
    body = r.json()

    assert {"recursive", "markdown", "code", "pdf"} <= {c["name"] for c in body["chunkers"]}
    assert {"stub", "bge-m3"} <= {e["name"] for e in body["embedders"]}
    assert {"bm25-only", "pgvector-hybrid"} <= {r_["name"] for r_ in body["retrievers"]}
    assert {"noop", "bge-reranker-v2-m3"} <= {r_["name"] for r_ in body["rerankers"]}
    assert {"stub"} <= {m["name"] for m in body["llms"]}


async def test_stages_reports_metadata(client: AsyncClient) -> None:
    body = (await client.get(STAGES)).json()
    embedders = {e["name"]: e for e in body["embedders"]}
    assert embedders["stub"]["dim"] == 64
    assert embedders["stub"]["model_id"] == "stub@1.0"
    assert embedders["bge-m3"]["dim"] == 1024
    chunkers = {c["name"]: c for c in body["chunkers"]}
    assert chunkers["recursive"]["version"]


async def test_stages_reports_the_configured_defaults(client: AsyncClient) -> None:
    body = (await client.get(STAGES)).json()
    # The test settings pin the offline-safe stages.
    assert body["defaults"] == {
        "chunker": "recursive",
        "embedder": "bge-m3",
        "retriever": "bm25-only",
        "reranker": "noop",
        "llm": "stub",
    }


async def test_stages_requires_permission(raw_client: AsyncClient) -> None:
    r = await raw_client.get(STAGES)
    assert r.status_code == 401
