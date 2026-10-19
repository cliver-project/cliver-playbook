"""Word ``.docx`` chunker.

Reads the OOXML body in document order with ``python-docx`` and hands
the resulting blocks to the shared section/table helpers. The output
is therefore consistent with the HTML chunker: heading-delimited
sections, optional heading-path prefixes, and tables rendered as
markdown or HTML.

Design notes:

* Only the main document body is read. Headers, footers, footnotes,
  comments, and text boxes are outside ``document.element.body`` and
  are intentionally excluded.
* Heading levels come from ``w:outlineLvl`` first (the semantic
  property Word writes for outline headings), then from the style id
  (``Heading1`` … ``Heading9``, ``Title``), then from the style name
  (``Heading 1``). Localized Word installations keep the built-in
  style ids in English, so this order is robust across UI languages.
* Tables use ``row.cells`` as-is. Vertically or horizontally merged
  cells repeat their text through ``row.cells``; keeping that
  repetition preserves column alignment for the common two-column
  key/value table.
* ``python-docx`` is imported inside ``split`` so importing the
  chunking folder (or this module) does not require the dependency
  until a DOCX is actually chunked.
"""

from __future__ import annotations

import io
import re

from .base import (
    Chunk,
    ChunkerInputError,
    Document,
    EmptyDocumentError,
    OptionsInput,
)
from .options import DocxOptions
from .sections import (
    Block,
    build_sections,
    chunk_sections,
    heading_block,
    table_block,
    text_block,
)
from .tables import TableData

VERSION = "1.0.0"

# Compound File Binary Format magic: legacy .doc, and also encrypted
# OOXML packages. Both need a different tool than python-docx.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_HEADING_STYLE_ID = re.compile(r"Heading([1-9])$")
_HEADING_STYLE_NAME = re.compile(r"heading\s+([1-9])", re.IGNORECASE)


def _coerce_options(options: OptionsInput | None) -> DocxOptions:
    if options is None:
        return DocxOptions()
    if isinstance(options, DocxOptions):
        return options
    return DocxOptions.model_validate(options)


def _is_toc(paragraph) -> bool:
    style = paragraph.style
    if style is None:
        return False
    style_id = (style.style_id or "").lower()
    style_name = (style.name or "").lower()
    return style_id.startswith("toc") or style_name.startswith("toc")


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
    # iter_inner_content includes hyperlink text; older python-docx
    # versions only expose .text, which is the fallback.
    try:
        return "".join(item.text for item in paragraph.iter_inner_content())
    except AttributeError:
        return paragraph.text


def _table_data(table) -> TableData:
    rows = [[cell.text for cell in row.cells] for row in table.rows]
    if not rows:
        return TableData()
    return TableData(header_rows=[rows[0]], body_rows=rows[1:])


def _blocks(document, options: DocxOptions) -> list[Block]:
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blocks: list[Block] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            if options.drop_toc and _is_toc(paragraph):
                continue
            text = _paragraph_text(paragraph).strip()
            if not text:
                continue
            level = _heading_level(paragraph)
            blocks.append(heading_block(level, text) if level else text_block(text))
        elif isinstance(child, CT_Tbl):
            data = _table_data(Table(child, document))
            if data.header_rows or data.body_rows:
                blocks.append(table_block(data))
    return blocks


class DocxChunker:
    """Word ``.docx`` chunker with heading-aware sections."""

    name = "docx"
    version = VERSION
    options_model = DocxOptions

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        options: OptionsInput | None = None,
    ) -> list[Chunk]:
        if not isinstance(doc.raw, bytes):
            raise ChunkerInputError("DOCX input must be bytes")
        if doc.raw.startswith(_OLE_MAGIC):
            raise ChunkerInputError(
                "legacy .doc or encrypted OOXML is not supported; save the file as .docx"
            )

        parsed = _coerce_options(options)

        from docx import Document as DocxDocument

        try:
            document = DocxDocument(io.BytesIO(doc.raw))
        except Exception as exc:  # python-docx raises several parser-specific types
            raise ChunkerInputError(
                "not a valid .docx file; save the document as Word .docx and retry"
            ) from exc

        blocks = _blocks(document, parsed)
        if not blocks:
            raise EmptyDocumentError("DOCX produced no extractable text")

        sections = build_sections(
            blocks,
            heading_based=parsed.heading_based,
            max_heading_level=parsed.max_heading_level,
        )
        chunks = chunk_sections(
            sections,
            document_id=doc.id,
            source_version=doc.source_version,
            metadata=dict(doc.metadata),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            table_format=parsed.table_format,
            include_tables=parsed.include_tables,
            include_heading_path=parsed.include_heading_path,
        )
        if not chunks:
            raise EmptyDocumentError("DOCX produced no extractable text")
        return chunks


__all__ = ["DocxChunker"]
