"""Parsers turn source bytes into structural blocks before masking.

The parser stage is what lets the governance pipeline accept binary
documents without teaching every downstream stage about PDF or DOCX.
The tests pin the block contract, page locators and parser selection;
the exact third-party extraction is mocked where it would need a real
file.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cliver_playbook.app.rag_governance.stages.base import SourceDocument
from cliver_playbook.app.rag_governance.stages.parser import (
    DocxParser,
    ParserError,
    PdfParser,
    TextParser,
    _partition_pdf,
    select_parser,
)


def _text_document(text: str, *, mime: str = "text/markdown", name: str = "notes.md"):
    return SourceDocument(
        source_uri=name,
        title="Notes",
        mime_type=mime,
        content=text.encode(),
        metadata={"filename": name},
    )


def test_text_parser_emits_headings_and_paragraph_blocks() -> None:
    parsed = TextParser().parse(_text_document("# Chapter\nintro\n\n## Clause\nbody text\n"))

    assert [(block.kind, block.level, block.text) for block in parsed.blocks] == [
        ("heading", 1, "Chapter"),
        ("text", 0, "intro"),
        ("heading", 2, "Clause"),
        ("text", 0, "body text"),
    ]


def test_text_parser_rejects_non_utf8_input() -> None:
    document = SourceDocument(
        source_uri="bad.txt",
        title="Bad",
        mime_type="text/plain",
        content=b"\xff\xfe\x00",
        metadata={"filename": "bad.txt"},
    )
    with pytest.raises(ParserError, match="UTF-8"):
        TextParser().parse(document)


def _element(element_type: str, text: str, page: int, **metadata) -> object:
    cls = type(element_type, (), {})
    element = cls()
    element.text = text
    element.metadata = SimpleNamespace(page_number=page, **metadata)
    return element


def test_pdf_parser_keeps_page_locators_and_splits_pages() -> None:
    elements = [
        _element("Title", "Chapter one", 1, category_depth=0),
        _element("NarrativeText", "Body on page one.", 1),
        _element("NarrativeText", "Body on page two.", 2),
    ]

    with patch(
        "cliver_playbook.app.rag_governance.stages.parser._partition_pdf",
        return_value=elements,
    ):
        parsed = PdfParser().parse(
            SourceDocument(
                source_uri="archive.pdf",
                title="Archive",
                mime_type="application/pdf",
                content=b"%PDF",
                metadata={"filename": "archive.pdf"},
            )
        )

    assert [block.text for block in parsed.blocks if block.kind != "page_break"] == [
        "Chapter one",
        "Body on page one.",
        "Body on page two.",
    ]
    assert parsed.blocks[0].kind == "heading"
    assert parsed.blocks[0].locator == {"page": 1}
    assert any(block.kind == "page_break" for block in parsed.blocks)
    assert parsed.blocks[-1].locator == {"page": 2}


def test_pdf_parser_rejects_an_image_only_document() -> None:
    with (
        patch(
            "cliver_playbook.app.rag_governance.stages.parser._partition_pdf",
            return_value=[],
        ),
        pytest.raises(ParserError, match="image-only"),
    ):
        PdfParser().parse(
            SourceDocument(
                source_uri="scan.pdf",
                title="Scan",
                mime_type="application/pdf",
                content=b"%PDF",
                metadata={"filename": "scan.pdf"},
            )
        )


def test_docx_parser_emits_heading_text_and_table_blocks() -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("Chapter one", level=1)
    document.add_paragraph("Body text.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Revenue"
    table.cell(1, 1).text = "1200"
    buffer = io.BytesIO()
    document.save(buffer)

    parsed = DocxParser().parse(
        SourceDocument(
            source_uri="archive.docx",
            title="Archive",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=buffer.getvalue(),
            metadata={"filename": "archive.docx"},
        )
    )

    assert [(block.kind, block.level) for block in parsed.blocks] == [
        ("heading", 1),
        ("text", 0),
        ("table", 0),
    ]
    assert parsed.blocks[0].text == "Chapter one"
    assert "| Name | Value |" in parsed.blocks[2].text


def test_pdf_partition_gives_the_extractor_a_seekable_stream(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_partition(*, file, strategy):
        captured["file"] = file
        captured["strategy"] = strategy
        return []

    monkeypatch.setattr("unstructured.partition.pdf.partition_pdf", fake_partition)

    assert _partition_pdf(b"%PDF-1.4") == []
    assert hasattr(captured["file"], "seek")
    assert captured["strategy"] == "fast"


def test_parser_selection_uses_mime_and_extension() -> None:
    cases = [
        (_text_document("# A"), TextParser),
        (
            SourceDocument(
                source_uri="a.pdf",
                title="A",
                mime_type="application/pdf",
                content=b"%PDF",
                metadata={},
            ),
            PdfParser,
        ),
        (
            SourceDocument(
                source_uri="a.docx",
                title="A",
                mime_type="application/octet-stream",
                content=b"PK",
                metadata={"filename": "a.docx"},
            ),
            DocxParser,
        ),
    ]

    for document, expected_type in cases:
        assert isinstance(select_parser(document), expected_type)

    with pytest.raises(ParserError, match="no parser"):
        select_parser(
            SourceDocument(
                source_uri="a.bin",
                title="A",
                mime_type="application/octet-stream",
                content=b"\x00",
                metadata={"filename": "a.bin"},
            )
        )
