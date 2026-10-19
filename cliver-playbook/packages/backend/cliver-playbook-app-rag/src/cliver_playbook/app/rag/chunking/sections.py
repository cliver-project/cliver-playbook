"""Heading-aware section assembly shared by the DOCX and HTML chunkers.

Parsers walk their source in document order and emit :class:`Block`
objects. This module turns that flat stream into sections:

* a heading at a level within ``max_heading_level`` closes the
  previous section and opens a new one;
* the heading stack pops deeper-or-equal headings, so a sibling
  heading does not inherit the previous sibling's children;
* blocks before the first heading live in a section with an empty
  heading path;
* headings deeper than ``max_heading_level`` become body text, and
  ``heading_based=False`` disables sectioning entirely.

Each section's body is split with the same recursive splitter and
character offsets as the default chunker. The heading path is both
stored in ``metadata["section_path"]`` (using the markdown chunker's
``"H2#Scope"`` convention) and, unless disabled, prefixed to the
chunk text so a retrieved chunk is understandable in isolation.

Source offsets are relative to the section body, not to the whole
document. This matches the markdown chunker, whose sections are
produced by a splitter without global offsets; keeping the
convention identical avoids implying a precision the parsers cannot
provide.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .base import Chunk, SourceOffset, make_chunk_id, split_text_with_offsets
from .tables import TableData, TableFormat, table_text_parts


@dataclass(frozen=True)
class Heading:
    """One entry in a section's heading path."""

    level: int
    text: str


@dataclass
class Block:
    """One parser output: a heading, a text block, or a table."""

    kind: str
    text: str = ""
    level: int = 0
    table: TableData | None = None


@dataclass
class Section:
    """A heading path and the blocks under it."""

    heading_path: list[Heading] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)


def heading_block(level: int, text: str) -> Block:
    """Build a heading block."""
    return Block(kind="heading", text=text, level=level)


def text_block(text: str) -> Block:
    """Build a body-text block."""
    return Block(kind="text", text=text)


def table_block(table: TableData) -> Block:
    """Build a table block."""
    return Block(kind="table", table=table)


def build_sections(
    blocks: Iterable[Block],
    *,
    heading_based: bool = True,
    max_heading_level: int = 6,
) -> list[Section]:
    """Group blocks into heading-delimited sections."""
    sections: list[Section] = []
    stack: list[Heading] = []
    current: list[Block] = []
    current_path: list[Heading] = []

    def flush() -> None:
        if current:
            sections.append(Section(heading_path=list(current_path), blocks=list(current)))
            current.clear()

    for block in blocks:
        if block.kind == "heading":
            text = block.text.strip()
            if not text:
                continue
            if heading_based and 1 <= block.level <= max_heading_level:
                flush()
                while stack and stack[-1].level >= block.level:
                    stack.pop()
                stack.append(Heading(level=block.level, text=text))
                current_path = list(stack)
            else:
                current.append(text_block(text))
            continue

        if block.kind == "text":
            text = block.text.strip()
            if text:
                current.append(text_block(text))
            continue

        if block.kind == "table" and block.table is not None:
            current.append(block)

    flush()
    return sections


def chunk_sections(
    sections: Iterable[Section],
    *,
    document_id: str,
    source_version: str,
    metadata: dict,
    chunk_size: int,
    chunk_overlap: int,
    table_format: TableFormat = "markdown",
    include_tables: bool = True,
    include_heading_path: bool = True,
) -> list[Chunk]:
    """Turn sections into content-hash IDed chunks with global ordinals."""
    chunks: list[Chunk] = []
    ordinal = 0

    for section in sections:
        block_texts: list[str] = []
        for block in section.blocks:
            if block.kind == "table":
                if not include_tables or block.table is None:
                    continue
                block_texts.extend(
                    part
                    for part in table_text_parts(
                        block.table,
                        chunk_size=chunk_size,
                        table_format=table_format,
                    )
                    if part.strip()
                )
                continue
            text = block.text.strip()
            if text:
                block_texts.append(text)

        if not block_texts:
            continue

        body = "\n\n".join(block_texts)
        if len(body) <= chunk_size:
            pieces = [(body, 0, len(body))]
        else:
            pieces = split_text_with_offsets(
                text=body,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

        section_path = [f"H{heading.level}#{heading.text}" for heading in section.heading_path]
        prefix = ""
        if include_heading_path and section.heading_path:
            prefix = " > ".join(heading.text for heading in section.heading_path) + "\n\n"

        for piece, start, end in pieces:
            if not piece.strip():
                continue
            text = f"{prefix}{piece}" if prefix else piece
            chunks.append(
                Chunk(
                    id=make_chunk_id(document_id, source_version, ordinal, text),
                    text=text,
                    metadata={**metadata, "section_path": section_path},
                    parent_id=None,
                    source_offset=SourceOffset(start=start, end=end, unit="char"),
                )
            )
            ordinal += 1

    return chunks


__all__ = [
    "Block",
    "Heading",
    "Section",
    "build_sections",
    "chunk_sections",
    "heading_block",
    "table_block",
    "text_block",
]
