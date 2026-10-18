"""Stage-discovery endpoint: the UI's source of selectable stage names."""

from __future__ import annotations

from httpx import AsyncClient

STAGES = "/api/v1/rag/stages"


async def test_stages_lists_every_registry(client: AsyncClient) -> None:
    r = await client.get(STAGES)
    assert r.status_code == 200, r.text
    body = r.json()

    assert {"recursive", "markdown", "code", "pdf"} <= {c["name"] for c in body["chunkers"]}
    assert {"stub", "bge-m3", "bge-base-zh-v1.5"} <= {e["name"] for e in body["embedders"]}
    assert {"bm25-only", "pgvector-hybrid"} <= {r_["name"] for r_ in body["retrievers"]}
    assert {"noop", "bge-reranker-v2-m3"} <= {r_["name"] for r_ in body["rerankers"]}
    assert {"stub"} <= {m["name"] for m in body["llms"]}


async def test_stages_reports_metadata(client: AsyncClient) -> None:
    body = (await client.get(STAGES)).json()
    embedders = {e["name"]: e for e in body["embedders"]}
    assert embedders["stub"]["dim"] == 64
    assert embedders["stub"]["model_id"] == "stub@1.0"
    assert embedders["bge-m3"]["dim"] == 1024
    assert embedders["bge-base-zh-v1.5"]["dim"] == 768
    assert embedders["bge-base-zh-v1.5"]["model_id"].startswith("BAAI/bge-base-zh-v1.5@")
    chunkers = {c["name"]: c for c in body["chunkers"]}
    assert chunkers["recursive"]["version"]


async def test_stages_reports_the_configured_defaults(client: AsyncClient) -> None:
    body = (await client.get(STAGES)).json()
    # The test fixture pins every offline-safe stage explicitly, so this
    # assertion is independent of the checked-in app.yaml.
    assert body["defaults"] == {
        "chunker": "recursive",
        "embedder": "stub",
        "retriever": "bm25-only",
        "reranker": "noop",
        "llm": "stub",
    }


async def test_stages_reports_retriever_modes(client: AsyncClient) -> None:
    """The UI filters modes by capability instead of offering a 422.

    Only retrievers declare modes; the other stages carry ``null`` so a
    client can tell "not applicable" from an empty capability set.
    """
    body = (await client.get(STAGES)).json()
    retrievers = {r["name"]: r for r in body["retrievers"]}
    assert retrievers["bm25-only"]["modes"] == ["hybrid", "sparse"]
    assert set(retrievers["pgvector-hybrid"]["modes"]) == {"dense", "sparse", "hybrid"}
    assert body["chunkers"][0]["modes"] is None
    assert body["embedders"][0]["modes"] is None


async def test_stages_reports_corpus_embedders(client: AsyncClient) -> None:
    """The chat page must offer query embedders that actually indexed rows."""
    assert (await client.get(STAGES)).json()["corpus"]["embedders"] == []

    import io

    files = {"file": ("corpus.txt", io.BytesIO(b"Hello. " * 50), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    uploaded = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]
    # Pending documents do not count: their vectors do not exist yet.
    assert (await client.get(STAGES)).json()["corpus"]["embedders"] == []

    indexed = await client.post(f"/api/v1/rag/documents/{document_id}/index")
    assert indexed.status_code == 200, indexed.text
    assert (await client.get(STAGES)).json()["corpus"]["embedders"] == ["stub"]


async def test_stages_requires_permission(raw_client: AsyncClient) -> None:
    r = await raw_client.get(STAGES)
    assert r.status_code == 401
