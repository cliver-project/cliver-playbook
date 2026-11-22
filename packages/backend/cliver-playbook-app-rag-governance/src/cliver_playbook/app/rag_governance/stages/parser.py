"""Parsers turn source bytes into structural blocks.

This is the governance pipeline's normalization boundary: every source
format is reduced to the same small block vocabulary
(``heading`` / ``text`` / ``table`` / ``page_break``) before cleaning,
masking, sectioning and chunking. The rest of the pipeline therefore
never branches on MIME type.

The block contract is intentionally smaller than a full document IR.
It carries what the retrieval loop needs today: heading-driven
sections and page locators. Richer structure (clauses, blocks, table
cells) stays in ``metadata`` until a consumer needs it as a queryable
node, which keeps this module from becoming a second document model.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from pydantic import BaseModel

from cliver_playbook.app.rag.chunking.tables import TableData, render_table
from cliver_playbook.app.rag_governance.stages.base import (
    ParsedBlock,
    ParsedDocument,
    Parser,
    SourceDocument,
)
from cliver_playbook.app.rag_governance.stages.registry import Registry


class ParserError(ValueError):
    """The source cannot be parsed, or no parser is configured for it."""


class ParserOptions(BaseModel):
    """Options shared by the built-in parsers. Empty in v1."""


_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_TRAILING_HASHES = re.compile(r"[ \t]+#+[ \t]*$")
_CODE_FENCE = re.compile(r"^\s*```")

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _decode_text(document: SourceDocument) -> str:
    content = document.content
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParserError(f"source document {document.source_uri!r} is not UTF-8 text") from exc


class TextParser:
    """Plain text and Markdown, split into heading and paragraph blocks."""

    name = "text"
    version = "1"
    options_model = ParserOptions

    def parse(
        self,
        document: SourceDocument,
        options: BaseModel | None = None,
    ) -> ParsedDocument:
        del options
        text = _decode_text(document)
        blocks: list[ParsedBlock] = []
        paragraph: list[str] = []
        in_code = False

        def flush_paragraph() -> None:
            if paragraph:
                blocks.append(ParsedBlock(kind="text", text="\n".join(paragraph)))
                paragraph.clear()

        for line in text.splitlines():
            if _CODE_FENCE.match(line):
                in_code = not in_code
                paragraph.append(line)
                continue
            match = None if in_code else _HEADING.match(line)
            if match is not None:
                flush_paragraph()
                level = len(match.group(1))
                title = _TRAILING_HASHES.sub("", match.group(2)).strip()
                if title:
                    blocks.append(ParsedBlock(kind="heading", text=title, level=level))
                continue
            if not in_code and not line.strip():
                flush_paragraph()
                continue
            paragraph.append(line)

        flush_paragraph()
        if not blocks:
            raise ParserError(f"source document {document.source_uri!r} is empty")
        return ParsedDocument(blocks=blocks)


def _partition_pdf(pdf_bytes: bytes) -> list:
    """Thin wrapper so tests can replace the heavy extractor.

    ``partition_pdf`` expects a seekable file-like object; passing raw
    bytes fails inside its own ``file.seek(0)``. A BytesIO keeps the
    public parser input as bytes without leaking that detail upward.
    """
    from unstructured.partition.pdf import partition_pdf

    return partition_pdf(file=io.BytesIO(pdf_bytes), strategy="fast")


class PdfParser:
    """Text PDFs via unstructured's fast strategy (no OCR)."""

    name = "pdf"
    version = "1"
    options_model = ParserOptions

    def parse(
        self,
        document: SourceDocument,
        options: BaseModel | None = None,
    ) -> ParsedDocument:
        del options
        if not isinstance(document.content, bytes):
            raise ParserError("PDF input must be bytes")
        elements = _partition_pdf(document.content)
        blocks: list[ParsedBlock] = []
        pages: list[int] = []
        previous_page: int | None = None

        for element in elements:
            text = (getattr(element, "text", "") or "").strip()
            if not text:
                continue
            metadata = getattr(element, "metadata", None)
            page = getattr(metadata, "page_number", None) if metadata is not None else None
            locator = {"page": page} if isinstance(page, int) else {}
            if isinstance(page, int):
                pages.append(page)
                if previous_page is not None and page != previous_page:
                    blocks.append(ParsedBlock(kind="page_break", locator={"page": page}))
                previous_page = page

            element_type = type(element).__name__
            if element_type == "Title":
                depth = getattr(metadata, "category_depth", None) if metadata is not None else None
                level = depth + 1 if isinstance(depth, int) else 1
                blocks.append(
                    ParsedBlock(
                        kind="heading",
                        text=text,
                        level=max(1, min(level, 6)),
                        locator=locator,
                        metadata={"element_type": element_type},
                    )
                )
            elif element_type == "Table":
                blocks.append(
                    ParsedBlock(
                        kind="table",
                        text=text,
                        locator=locator,
                        metadata={"element_type": element_type},
                    )
                )
            else:
                blocks.append(
                    ParsedBlock(
                        kind="text",
                        text=text,
                        locator=locator,
                        metadata={"element_type": element_type},
                    )
                )

        if not any(block.kind != "page_break" for block in blocks):
            raise ParserError("PDF produced no extractable text (likely an image-only scan)")
        metadata = {"page_count": max(pages)} if pages else {}
        return ParsedDocument(blocks=blocks, metadata=metadata)


# DOCX heading detection is intentionally the same rule the rag
# DOCX chunker uses (outline level, then style id, then style name).
# Keeping it local is deliberate: the chunker consumes already-split
# chunks, while this parser needs the pre-split document order.
_HEADING_STYLE_ID = re.compile(r"Heading([1-9])$")
_HEADING_STYLE_NAME = re.compile(r"heading\s+([1-9])", re.IGNORECASE)
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _heading_level(paragraph) -> int | None:
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.outlineLvl is not None:
        value = p_pr.outlineLvl.val
        if value is not None and 0 <= value <= 8:
            return value + 1

    style = paragraph.style
    if style is None:
        return None

    style_id = style.style_id or ""
    match = _HEADING_STYLE_ID.match(style_id)
    if match:
        return int(match.group(1))
    if style_id.lower() == "title":
        return 1

    match = _HEADING_STYLE_NAME.match(style.name or "")
    if match:
        return int(match.group(1))
    return None


def _paragraph_text(paragraph) -> str:
    try:
        return "".join(item.text for item in paragraph.iter_inner_content())
    except AttributeError:
        return paragraph.text


def _table_text(table) -> str:
    rows = [[cell.text for cell in row.cells] for row in table.rows]
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    data = TableData(header_rows=[rows[0]], body_rows=rows[1:])
    return render_table(data, table_format="markdown")


class DocxParser:
    """Word ``.docx`` parsed in document order before any chunking."""

    name = "docx"
    version = "1"
    options_model = ParserOptions

    def parse(
        self,
        document: SourceDocument,
        options: BaseModel | None = None,
    ) -> ParsedDocument:
        del options
        if not isinstance(document.content, bytes):
            raise ParserError("DOCX input must be bytes")
        if document.content.startswith(_OLE_MAGIC):
            raise ParserError(
                "legacy .doc or encrypted OOXML is not supported; save the file as .docx"
            )

        from docx import Document as DocxDocument

        try:
            parsed = DocxDocument(io.BytesIO(document.content))
        except Exception as exc:  # python-docx raises several parser-specific types
            raise ParserError(
                "not a valid .docx file; save the document as Word .docx and retry"
            ) from exc

        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        blocks: list[ParsedBlock] = []
        for child in parsed.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraph = Paragraph(child, parsed)
                text = _paragraph_text(paragraph).strip()
                if not text:
                    continue
                level = _heading_level(paragraph)
                blocks.append(
                    ParsedBlock(
                        kind="heading" if level else "text",
                        text=text,
                        level=level or 0,
                    )
                )
            elif isinstance(child, CT_Tbl):
                text = _table_text(Table(child, parsed))
                if text:
                    blocks.append(ParsedBlock(kind="table", text=text))

        if not blocks:
            raise ParserError("DOCX produced no extractable text")
        return ParsedDocument(blocks=blocks)


parsers: Registry[Parser] = Registry("parser")
parsers.register(TextParser.name, TextParser)
parsers.register(PdfParser.name, PdfParser)
parsers.register(DocxParser.name, DocxParser)


def parser_name_for(document: SourceDocument) -> str:
    """Pick a built-in parser from MIME type, then filename suffix."""
    mime = (document.mime_type or "").lower()
    filename = str(document.metadata.get("filename") or document.source_uri or "")
    suffix = Path(filename).suffix.lower()

    if mime == "application/pdf" or suffix == ".pdf":
        return PdfParser.name
    if mime == _DOCX_MIME or suffix in {".docx", ".doc"}:
        # The legacy .doc path reaches DocxParser so it can return the
        # actionable "save as .docx" message instead of "no parser".
        return DocxParser.name
    if mime.startswith("text/") or suffix in {".md", ".markdown", ".txt", ".text"}:
        return TextParser.name
    raise ParserError(
        f"no parser for {document.mime_type!r} ({filename!r}); "
        "configure parsing.parser or register a parser"
    )


def select_parser(document: SourceDocument, name: str = "auto") -> Parser:
    """Return the configured parser, or infer one for ``auto``."""
    if name and name != "auto":
        return parsers.get(name)
    return parsers.get(parser_name_for(document))


__all__ = [
    "DocxParser",
    "ParserError",
    "ParserOptions",
    "PdfParser",
    "TextParser",
    "parser_name_for",
    "parsers",
    "select_parser",
]
