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

from docx import Document as DocxDocument
from httpx import AsyncClient

UPLOAD = "/api/v1/rag/documents/upload"
BASE = "/api/v1/rag/documents"

HTML_PAGE = b"""
<html><body>
  <h1>Policy</h1>
  <p>intro</p>
  <h2>Scope</h2>
  <p>scope body</p>
</body></html>
"""


def _docx_bytes() -> bytes:
    document = DocxDocument()
    document.add_heading("Policy", level=1)
    document.add_paragraph("intro")
    document.add_heading("Scope", level=2)
    document.add_paragraph("scope body")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _html_form(**extra: str) -> dict[str, str]:
    return {
        "chunker": "html",
        "embedder": "stub",
        "chunk_size": "512",
        "chunk_overlap": "0",
        **extra,
    }


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


async def test_upload_persists_the_effective_chunker_config(client: AsyncClient) -> None:
    """Defaults are part of the recorded configuration, not implicit."""
    files = {"file": ("policy.html", io.BytesIO(HTML_PAGE), "text/html")}
    r = await client.post(UPLOAD, files=files, data=_html_form())
    assert r.status_code == 201, r.text

    body = r.json()
    config = body["chunker_config"]
    assert config["version"] == "1.0.0"
    assert config["chunk_size"] == 512
    assert config["chunk_overlap"] == 0
    assert config["options"]["heading_based"] is True
    assert config["options"]["table_format"] == "markdown"

    document = (await client.get(f"{BASE}/{body['document_id']}")).json()
    assert document["chunker_config"] == config


async def test_upload_docx_runs_the_docx_chunker(client: AsyncClient) -> None:
    """A real Word file uploads through the format-specific parser."""
    files = {
        "file": (
            "policy.docx",
            io.BytesIO(_docx_bytes()),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    data = {"chunker": "docx", "embedder": "stub", "chunk_size": "512", "chunk_overlap": "0"}
    r = await client.post(UPLOAD, files=files, data=data)
    assert r.status_code == 201, r.text

    body = r.json()
    assert body["chunker_config"]["options"]["drop_toc"] is True
    texts = [chunk["text"] for chunk in body["preview_chunks"]]
    assert any("Policy > Scope" in text for text in texts)


async def test_reupload_with_options_updates_the_same_document(client: AsyncClient) -> None:
    """The agreed re-chunk path is a re-upload, so options must apply to it."""
    first = await client.post(
        UPLOAD,
        files={"file": ("policy.html", io.BytesIO(HTML_PAGE), "text/html")},
        data=_html_form(),
    )
    assert first.status_code == 201, first.text
    document_id = first.json()["document_id"]
    assert first.json()["chunker_config"]["options"]["heading_based"] is True
    assert len(first.json()["preview_chunks"]) == 2

    second = await client.post(
        UPLOAD,
        files={"file": ("policy.html", io.BytesIO(HTML_PAGE), "text/html")},
        data=_html_form(chunker_options='{"heading_based": false}'),
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["document_id"] == document_id
    assert body["version"] == 2
    assert body["chunker_config"]["options"]["heading_based"] is False
    # One section, so the two headings are body text in a single chunk.
    assert len(body["preview_chunks"]) == 1
    assert "Policy" in body["preview_chunks"][0]["text"]
    assert "Scope" in body["preview_chunks"][0]["text"]
    assert " > " not in body["preview_chunks"][0]["text"]

    document = (await client.get(f"{BASE}/{document_id}")).json()
    assert document["version"] == 2
    assert document["chunker_config"]["options"]["heading_based"] is False


async def test_upload_rejects_invalid_options_without_a_failed_row(
    client: AsyncClient,
) -> None:
    def post(options: str):
        return client.post(
            UPLOAD,
            files={"file": ("policy.html", io.BytesIO(HTML_PAGE), "text/html")},
            data=_html_form(chunker_options=options),
        )

    malformed = await post("not-json")
    assert malformed.status_code == 422
    assert "valid JSON" in malformed.json()["detail"]
    assert (await client.get(BASE)).json()["items"] == []

    unknown = await post('{"nope": true}')
    assert unknown.status_code == 422
    detail = unknown.json()["detail"]
    assert isinstance(detail, list)
    assert any("nope" in error["loc"] for error in detail)
    assert (await client.get(BASE)).json()["items"] == []

    oversized = await post("x" * 5000)
    assert oversized.status_code == 422
    assert "at most 4096 bytes" in oversized.json()["detail"]
    assert (await client.get(BASE)).json()["items"] == []


async def test_upload_rejects_options_for_a_chunker_without_a_model(
    client: AsyncClient,
) -> None:
    """Third-party chunkers written before the options contract still work."""

    class _BareChunker:
        name = "bare"
        version = "0.0.1"

        def split(self, doc, *, chunk_size=512, chunk_overlap=64):
            return []

    files = {"file": ("hello.txt", io.BytesIO(b"Hello world."), "text/plain")}
    data = {"chunker": "bare", "embedder": "stub", "chunker_options": "{}"}
    with patch("cliver_playbook.app.rag.api.documents.get_chunker", return_value=_BareChunker()):
        r = await client.post(UPLOAD, files=files, data=data)

    assert r.status_code == 422
    assert "does not accept options" in r.json()["detail"]
    assert (await client.get(BASE)).json()["items"] == []


async def test_upload_rejects_an_invalid_html_selector_without_a_failed_row(
    client: AsyncClient,
) -> None:
    files = {"file": ("policy.html", io.BytesIO(HTML_PAGE), "text/html")}
    r = await client.post(
        UPLOAD,
        files=files,
        data=_html_form(chunker_options='{"content_selector": "div["}'),
    )

    assert r.status_code == 422
    assert "invalid content selector" in r.json()["detail"]
    assert (await client.get(BASE)).json()["items"] == []


async def test_upload_rejects_a_legacy_doc_and_records_the_failure(
    client: AsyncClient,
) -> None:
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
    files = {"file": ("legacy.doc", io.BytesIO(content), "application/msword")}
    data = {"chunker": "docx", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    r = await client.post(UPLOAD, files=files, data=data)

    assert r.status_code == 422
    assert "legacy .doc" in r.json()["detail"]

    items = (await client.get(BASE)).json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["failure_reason"] == "chunking_failed"
    assert items[0]["chunker_config"]["chunk_size"] == 64
    assert items[0]["chunker_config"]["options"]["drop_toc"] is True
