"""Document list/read/chunks endpoints and re-upload idempotency.

The knowledge base is shared in v1 (the spec's explicit non-goal:
"no multi-tenant isolation"), so the list endpoint returns every
document rather than filtering by caller.
"""

from __future__ import annotations

import io

from httpx import AsyncClient

BASE = "/api/v1/rag/documents"


async def _upload_and_index(client: AsyncClient, content: bytes, name: str = "x.txt") -> str:
    files = {"file": (name, io.BytesIO(content), "text/plain")}
    data = {
        "chunker": "recursive",
        "embedder": "stub",
        "chunk_size": "64",
        "chunk_overlap": "0",
    }
    r = await client.post(f"{BASE}/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    document_id = r.json()["document_id"]
    r2 = await client.post(f"{BASE}/{document_id}/index")
    assert r2.status_code == 200, r2.text
    return document_id


async def test_list_documents(client: AsyncClient) -> None:
    await _upload_and_index(client, b"Hello. " * 50)
    r = await client.get(BASE)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["chunker_id"] == "recursive"
    assert items[0]["embedder_id"] == "stub"
    assert items[0]["status"] == "indexed"
    assert items[0]["chunk_count"] > 0


async def test_get_document(client: AsyncClient) -> None:
    document_id = await _upload_and_index(client, b"Hello there. " * 30)
    r = await client.get(f"{BASE}/{document_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == document_id
    assert body["status"] == "indexed"
    assert body["mime_type"] == "text/plain"
    assert body["dim"] == 64


async def test_get_document_chunks(client: AsyncClient) -> None:
    document_id = await _upload_and_index(client, b"Hello. " * 50)
    r = await client.get(f"{BASE}/{document_id}/chunks")
    assert r.status_code == 200
    chunks = r.json()["items"]
    assert len(chunks) > 0
    assert all("text" in c and "ordinal" in c for c in chunks)
    assert [c["ordinal"] for c in chunks] == sorted(c["ordinal"] for c in chunks)


async def test_get_missing_document_returns_404(client: AsyncClient) -> None:
    r = await client.get(f"{BASE}/does-not-exist")
    assert r.status_code == 404


async def test_index_is_idempotent(client: AsyncClient) -> None:
    """Re-uploading the same file yields the same document id (content-hash),
    and re-indexing a document already marked indexed is a no-op."""
    content = b"The same content. " * 30
    doc_id_a = await _upload_and_index(client, content, name="same.txt")
    doc_id_b = await _upload_and_index(client, content, name="same.txt")
    assert doc_id_a == doc_id_b

    chunks_a = (await client.get(f"{BASE}/{doc_id_a}/chunks")).json()["items"]

    r2 = await client.post(f"{BASE}/{doc_id_a}/index")
    assert r2.status_code == 200
    chunks_b = (await client.get(f"{BASE}/{doc_id_a}/chunks")).json()["items"]
    assert chunks_b == chunks_a

    listed = (await client.get(BASE)).json()["items"]
    assert len(listed) == 1


async def test_list_requires_permission(raw_client: AsyncClient) -> None:
    r = await raw_client.get(BASE)
    assert r.status_code == 401
