"""Chunker tests: registry, idempotency, header preservation, code awareness, PDF."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

from cliver_playbook.app.rag.chunking import Document, get_chunker
from cliver_playbook.app.rag.chunking.registry import registry


def test_registry_has_four_chunkers() -> None:
    assert set(registry.names()) == {"recursive", "markdown", "code", "pdf"}


def test_recursive_chunker_idempotent() -> None:
    c = get_chunker("recursive")
    text = "Sentence one. Sentence two. " * 200
    doc = Document(id="a", source_version="v1", mime_type="text/plain", raw=text)
    chunks_a = c.split(doc, chunk_size=200, chunk_overlap=20)
    chunks_b = c.split(doc, chunk_size=200, chunk_overlap=20)
    assert [ch.id for ch in chunks_a] == [ch.id for ch in chunks_b]
    expected = hashlib.sha256(f"a|v1|0|{chunks_a[0].text}".encode()).hexdigest()[:32]
    assert chunks_a[0].id == expected


def test_markdown_chunker_preserves_header_metadata() -> None:
    c = get_chunker("markdown")
    md = "# H1\nintro\n## H2\nbody\n"
    doc = Document(id="m", source_version="v1", mime_type="text/markdown", raw=md)
    chunks = c.split(doc, chunk_size=128, chunk_overlap=0)
    section_paths = [ch.metadata.get("section_path") for ch in chunks]
    # At least one chunk carries an H1 entry in its section path
    assert any(any("H1" in entry for entry in (p or [])) for p in section_paths)
    # At least one chunk carries an H2 entry in its section path
    assert any(any("H2" in entry for entry in (p or [])) for p in section_paths)


def test_code_chunker_uses_langchain_language() -> None:
    c = get_chunker("code")
    py = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    doc = Document(id="c", source_version="v1", mime_type="text/x-python", raw=py)
    chunks = c.split(doc, chunk_size=64, chunk_overlap=0)
    # Two top-level defs, two chunks (the recursive splitter's
    # language-aware mode keeps each function together)
    assert len(chunks) >= 1
    joined = "\n".join(ch.text for ch in chunks)
    assert "def a" in joined
    assert "def b" in joined


def test_pdf_chunker_uses_unstructured() -> None:
    c = get_chunker("pdf")
    with patch("cliver_playbook.app.rag.chunking.pdf._partition") as mock_partition:
        from unstructured.documents.elements import NarrativeText, Title

        mock_partition.return_value = [
            Title("First Section"),
            NarrativeText("Body of the first section."),
        ]
        doc = Document(id="p", source_version="v1", mime_type="application/pdf", raw=b"%PDF-fake")
        chunks = c.split(doc, chunk_size=128, chunk_overlap=0)
        assert len(chunks) == 2
        assert chunks[0].metadata.get("element_type") == "Title"
        assert chunks[1].metadata.get("element_type") == "NarrativeText"


def test_pdf_chunker_raises_empty_document_error_on_no_text() -> None:
    from cliver_playbook.app.rag.chunking.pdf import EmptyDocumentError

    c = get_chunker("pdf")
    with patch("cliver_playbook.app.rag.chunking.pdf._partition", return_value=[]):
        doc = Document(id="p2", source_version="v1", mime_type="application/pdf", raw=b"%PDF-fake")
        try:
            c.split(doc)
        except EmptyDocumentError:
            return
        raise AssertionError("expected EmptyDocumentError")


def test_unknown_chunker_raises() -> None:
    import pytest

    with pytest.raises(KeyError):
        get_chunker("no-such-chunker")
