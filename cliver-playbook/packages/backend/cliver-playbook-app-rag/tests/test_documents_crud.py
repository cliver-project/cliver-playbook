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
    # The column exists and serializes even before the upload path starts
    # filling it (step 7 writes the effective configuration).
    assert "chunker_config" in body


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


async def test_index_response_names_the_embedder_version(client: AsyncClient) -> None:
    """The response must say which model version produced the vectors.

    ``embedder_version`` is the identity retrieval filters on; an
    idempotent re-index has to report it too, otherwise the UI cannot
    verify that a query embedder will actually match.
    """
    document_id = await _upload_and_index(client, b"Hello. " * 50)
    r = await client.post(f"{BASE}/{document_id}/index")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["embedder"] == "stub"
    assert body["embedder_version"] == "stub@1.0"


class _FakeEmbedder:
    """Deterministic embedder used to exercise the per-call override."""

    def __init__(self, ident: str = "test-fake@1.0", dim: int = 8) -> None:
        self.id = ident
        self.dim = dim
        self.max_input_tokens = 8192
        self.supports_query_document_modes = False

    def embed(self, texts, *, mode="document"):
        vector = [1.0] + [0.0] * (self.dim - 1)
        return [list(vector) for _ in texts]

    def estimate_tokens(self, text: str) -> int:
        return len(text.split())


def _register_fake_embedder(name: str = "test-fake", dim: int = 8) -> None:
    from cliver_playbook.app.rag.embedding.registry import names, register

    if name not in names():
        register(name, lambda: _FakeEmbedder(ident=f"{name}@1.0", dim=dim))


async def test_index_accepts_an_embedder_override(client: AsyncClient) -> None:
    """The user picks the embedder after reviewing the chunk preview.

    Re-indexing with an override must replace the stored vectors and
    update the document row, so the query-time embedder filter and the
    catalog's corpus stats agree with what is actually stored.
    """
    from sqlalchemy import select

    from cliver_playbook.app.basic import runtime
    from cliver_playbook.app.rag.models.entities import Chunk, ChunkEmbedding

    _register_fake_embedder()
    files = {"file": ("override.txt", io.BytesIO(b"Hello. " * 50), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    uploaded = await client.post(f"{BASE}/upload", files=files, data=data)
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]

    r = await client.post(f"{BASE}/{document_id}/index", params={"embedder": "test-fake"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["embedder"] == "test-fake"
    assert body["embedder_version"] == "test-fake@1.0"
    assert body["dim"] == 8

    doc = (await client.get(f"{BASE}/{document_id}")).json()
    assert doc["embedder_id"] == "test-fake"
    assert doc["dim"] == 8

    async with runtime.session_factory()() as db:
        versions = (
            (
                await db.execute(
                    select(ChunkEmbedding.embedder_version).where(
                        ChunkEmbedding.chunk_id.in_(
                            select(Chunk.id).where(Chunk.document_id == document_id)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    assert versions and set(versions) == {"test-fake@1.0"}


async def test_index_rejects_an_unknown_override_without_corrupting_the_document(
    client: AsyncClient,
) -> None:
    document_id = await _upload_and_index(client, b"Hello. " * 50)

    r = await client.post(f"{BASE}/{document_id}/index", params={"embedder": "no-such-embedder"})
    assert r.status_code == 422
    assert "unknown embedder" in r.json()["detail"]

    doc = (await client.get(f"{BASE}/{document_id}")).json()
    assert doc["status"] == "indexed"
    assert doc["embedder_id"] == "stub"


async def test_delete_document_removes_chunks_and_the_row(client: AsyncClient) -> None:
    document_id = await _upload_and_index(client, b"Hello. " * 50)

    r = await client.delete(f"{BASE}/{document_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"document_id": document_id, "deleted": True}

    assert (await client.get(f"{BASE}")).json()["items"] == []
    assert (await client.get(f"{BASE}/{document_id}")).status_code == 404
    assert (await client.get(f"{BASE}/{document_id}/chunks")).status_code == 404
    # Deleting twice is a 404, not a crash or a silent success.
    assert (await client.delete(f"{BASE}/{document_id}")).status_code == 404
