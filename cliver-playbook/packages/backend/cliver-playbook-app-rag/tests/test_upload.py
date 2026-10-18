"""Upload + index endpoint tests.

These pin the upload stage's four input classes from the plan's Review
Focus: a normal file (preview returned, status pending), an empty file
(422), an unknown chunker (422), and an image-only PDF (422 with the
"no extractable text" reason). The index endpoint is covered for the
happy path and for its own auth gate.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from httpx import AsyncClient

UPLOAD = "/api/v1/rag/documents/upload"


async def test_upload_creates_document_with_chunks(client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world. " * 50), "text/plain")}
    data = {
        "chunker": "recursive",
        "embedder": "stub",
        "chunk_size": "64",
        "chunk_overlap": "0",
    }
    r = await client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["chunk_count"] > 0
    assert len(body["preview_chunks"]) == body["chunk_count"]
    assert body["status"] == "pending"
    assert body["chunker"] == "recursive"
    assert body["embedder"] == "stub"
    for chunk in body["preview_chunks"]:
        assert {"ordinal", "text", "token_count", "chunk_id_prefix"} <= set(chunk)
        assert chunk["text"]
        assert chunk["token_count"] > 0


async def test_index_marks_document_indexed(client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world. " * 50), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    uploaded = await client.post(UPLOAD, files=files, data=data)
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]

    r = await client.post(f"/api/v1/rag/documents/{document_id}/index")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_id"] == document_id
    assert body["status"] == "indexed"
    assert body["chunk_count"] == uploaded.json()["chunk_count"]


async def test_upload_rejects_empty_file(client: AsyncClient) -> None:
    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub"}
    r = await client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 422
    assert "empty" in r.json()["detail"].lower()


async def test_upload_rejects_unknown_chunker(client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world."), "text/plain")}
    data = {"chunker": "no-such-chunker", "embedder": "stub"}
    r = await client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 422
    assert "unknown chunker" in r.json()["detail"].lower()


async def test_upload_rejects_unknown_embedder(client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world."), "text/plain")}
    data = {"chunker": "recursive", "embedder": "no-such-embedder"}
    r = await client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 422
    assert "unknown embedder" in r.json()["detail"].lower()


async def test_upload_rejects_image_only_pdf(client: AsyncClient) -> None:
    files = {"file": ("scan.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")}
    data = {"chunker": "pdf", "embedder": "stub"}
    with patch("cliver_playbook.app.rag.chunking.pdf._partition", return_value=[]):
        r = await client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 422
    assert "no extractable text" in r.json()["detail"].lower()


async def test_upload_requires_bearer_token(raw_client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world."), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub"}
    r = await raw_client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 401


async def test_upload_rejects_a_file_over_the_size_cap(client: AsyncClient, monkeypatch) -> None:
    from cliver_playbook.app.rag.settings import settings as rag_settings

    monkeypatch.setattr(rag_settings.rag, "max_upload_bytes", 16)
    files = {"file": ("big.txt", io.BytesIO(b"x" * 64), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub"}

    r = await client.post(UPLOAD, files=files, data=data)

    assert r.status_code == 413
    assert "limit is 16 bytes" in r.json()["detail"]


async def test_failed_reupload_preserves_the_indexed_document(
    client: AsyncClient,
) -> None:
    """A rejected re-upload must not destroy a document that is live.

    Upload and index the file normally, then re-upload the same name and
    content through a chunker that rejects it. The document id is a
    content hash, so both requests target the same row; the failed
    attempt must leave the indexed version (chunks included) intact.
    """
    content = b"The indexed version stays searchable. " * 20
    files = {"file": ("keep.txt", io.BytesIO(content), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    uploaded = await client.post(UPLOAD, files=files, data=data)
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]
    indexed = await client.post(f"/api/v1/rag/documents/{document_id}/index")
    assert indexed.status_code == 200, indexed.text

    retry = {"file": ("keep.txt", io.BytesIO(content), "application/pdf")}
    with patch("cliver_playbook.app.rag.chunking.pdf._partition", return_value=[]):
        rejected = await client.post(
            UPLOAD, files=retry, data={"chunker": "pdf", "embedder": "stub"}
        )
    assert rejected.status_code == 422

    doc = (await client.get(f"/api/v1/rag/documents/{document_id}")).json()
    assert doc["status"] == "indexed"
    assert doc["failure_reason"] is None
    chunks = (await client.get(f"/api/v1/rag/documents/{document_id}/chunks")).json()["items"]
    assert chunks
