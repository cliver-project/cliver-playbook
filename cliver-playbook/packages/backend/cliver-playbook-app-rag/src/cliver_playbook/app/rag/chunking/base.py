"""Chunker protocol + the Document / Chunk / SourceOffset wire shapes.

The Chunker protocol is the seam every chunker implementation
satisfies. The protocol is structural (typing.Protocol), so a new
chunker type does not need to inherit — only provide the named
``name``, ``version``, and ``split(...)`` attributes.

Chunk IDs are content-hash (sha256 of document_id, source_version,
ordinal, text) so re-chunking the same document yields the same IDs
and re-indexing is an upsert.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Document(BaseModel):
    """A unit of content to be chunked.

    The ``raw`` field is the source bytes / string. Layout-aware
    parsers (PDF) may pre-parse it; the chunker that runs after a
    parser sees a string ``raw`` derived from the elements it
    produced.
    """

    id: str
    source_version: str = "v1"
    mime_type: str = "text/plain"
    raw: str | bytes = ""
    metadata: dict = Field(default_factory=dict)


class SourceOffset(BaseModel):
    """Position of a chunk within its source document."""

    start: int
    end: int
    unit: Literal["char", "byte", "token"] = "char"


class Chunk(BaseModel):
    """One chunk produced by a chunker."""

    id: str
    text: str
    metadata: dict = Field(default_factory=dict)
    parent_id: str | None = None
    source_offset: SourceOffset = Field(default_factory=lambda: SourceOffset(start=0, end=0))


def make_chunk_id(document_id: str, source_version: str, ordinal: int, text: str) -> str:
    """Stable content-hash ID for a chunk.

    Same document + same content + same ordinal + same text => same
    id. This is the property that makes re-indexing idempotent: the
    DB upsert by id never duplicates, and a chunker / embedder change
    that produces a different text produces a different id (and the
    old rows are simply orphaned, easy to clean up).
    """
    h = hashlib.sha256()
    h.update(document_id.encode())
    h.update(b"|")
    h.update(source_version.encode())
    h.update(b"|")
    h.update(str(ordinal).encode())
    h.update(b"|")
    h.update(text.encode())
    return h.hexdigest()[:32]


class Chunker(Protocol):
    """The chunker seam.

    Implementations: ``RecursiveChunker`` (default),
    ``MarkdownChunker``, ``CodeChunker``, ``PdfChunker``. Each lives
    in its own module and registers itself with the chunker registry
    at import.
    """

    name: str
    version: str

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> list[Chunk]: ...


def chunk_text_recursive(
    *,
    text: str,
    document_id: str,
    source_version: str,
    chunk_size: int,
    chunk_overlap: int,
    metadata: dict,
) -> list[Chunk]:
    """Split a string with the recursive character splitter and
    return content-hash IDed chunks.

    Used by the recursive and markdown chunkers (and the test
    fixture for unknown-chunker behavior). Exposed at module level
    so other chunkers can share the recursive fallback when their
    primary strategy produces an element that exceeds chunk_size.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    texts = splitter.split_text(text)
    chunks: list[Chunk] = []
    cursor = 0
    for ordinal, t in enumerate(texts):
        # Find the next occurrence of t in text starting at cursor.
        idx = text.find(t, cursor)
        if idx == -1:
            start = cursor
            end = cursor + len(t)
        else:
            start = idx
            end = idx + len(t)
        cursor = end
        chunks.append(
            Chunk(
                id=make_chunk_id(document_id, source_version, ordinal, t),
                text=t,
                metadata=metadata,
                parent_id=None,
                source_offset=SourceOffset(start=start, end=end, unit="char"),
            )
        )
    return chunks


__all__ = [
    "Chunk",
    "Chunker",
    "Document",
    "SourceOffset",
    "chunk_text_recursive",
    "make_chunk_id",
]


def _iter_chunks(chunks: Iterable[Chunk]) -> Iterable[Chunk]:
    """Helper for tests and consumers that want a stable iteration."""
    return list(chunks)
