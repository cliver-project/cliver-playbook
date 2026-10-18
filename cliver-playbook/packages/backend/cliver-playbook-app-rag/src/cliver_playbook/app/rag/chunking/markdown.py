"""Markdown header-aware chunker.

Splits first on Markdown headers (H1/H2/H3), then recurses on the
body of each header section. The resulting chunks carry a
``section_path`` metadata entry listing the headers in document
order — e.g. ``["H1#intro", "H2#authentication"]`` — so a retrieved
chunk always knows where in the document it came from.
"""

from __future__ import annotations

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from cliver_playbook.app.rag.chunking.base import (
    Chunk,
    Document,
    SourceOffset,
    make_chunk_id,
)

VERSION = "1.0.0"

_HEADERS = [("#", "H1"), ("##", "H2"), ("###", "H3")]


class MarkdownChunker:
    """Markdown / docs-aware chunker.

    For documents under ``chunk_size`` characters, returns one
    chunk carrying the full document's header path. For larger
    documents, splits on headers first, then on the body of each
    section with the recursive splitter. ``section_path`` is
    preserved on every chunk.
    """

    name = "markdown"
    version = VERSION

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> list[Chunk]:
        text = doc.raw if isinstance(doc.raw, str) else doc.raw.decode("utf-8")
        # Always run the header splitter first so every chunk knows
        # its section_path; the recursive fallback only fires when a
        # single section's body exceeds chunk_size.
        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=_HEADERS, strip_headers=False
        )
        sections = header_splitter.split_text(text)

        body_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunks: list[Chunk] = []
        ordinal = 0
        for section in sections:
            section_path = [
                f"{level}#{value}"
                for level, value in (section.metadata or {}).items()  # type: ignore[union-attr]
            ]
            body = section.page_content  # type: ignore[attr-defined]
            if len(body) <= chunk_size:
                pieces = [body]
            else:
                pieces = body_splitter.split_text(body)
            for piece in pieces:
                chunks.append(
                    Chunk(
                        id=make_chunk_id(doc.id, doc.source_version, ordinal, piece),
                        text=piece,
                        metadata={
                            **dict(doc.metadata),
                            "section_path": section_path,
                        },
                        parent_id=None,
                        source_offset=SourceOffset(start=0, end=len(piece), unit="char"),
                    )
                )
                ordinal += 1
        return chunks


def _extract_section_path(text: str) -> list[str]:
    """Best-effort section path from a document that fits in one chunk."""
    path: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for marker, level in _HEADERS:
            if stripped.startswith(marker + " "):
                path.append(f"{level}#{stripped[len(marker) :].strip()}")
                break
    return path
