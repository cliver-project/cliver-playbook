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
from collections.abc import Iterable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class EmptyDocumentError(ValueError):
    """The input produced no extractable text.

    Shared by every chunker that parses a structured format (PDF,
    DOCX, HTML). The upload endpoint turns it into 422 with an
    ``empty_after_parse`` failure reason rather than a generic
    chunking failure, because the problem is the input, not the
    chunker.
    """


class ChunkerInputError(ValueError):
    """The input is the wrong format or cannot be parsed.

    The canonical case is a legacy Word ``.doc`` sent to the DOCX
    chunker: it is a binary OLE file, not an OOXML ZIP. The message is
    shown to the user, so it must say what to do (save as ``.docx``),
    not merely what failed.
    """


class ChunkerOptionError(ValueError):
    """A chunker option is syntactically valid but semantically wrong.

    Example: an HTML ``content_selector`` that is not valid CSS. The
    upload endpoint returns 422 without recording a failed document,
    because the request, not the file, is wrong.
    """


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


OptionsInput = BaseModel | Mapping[str, Any]
"""What ``split`` accepts for ``options``.

Chunkers call ``options_model.model_validate(...)`` when they receive
anything other than an already-validated model, so a direct caller can
pass a plain dict and the HTTP layer can pass the model it validated.
"""


class Chunker(Protocol):
    """The chunker seam.

    Implementations: ``RecursiveChunker`` (default),
    ``MarkdownChunker``, ``CodeChunker``, ``PdfChunker``,
    ``DocxChunker``, ``HtmlChunker``. Each lives in its own module and
    registers itself with the chunker registry at import.

    ``options_model`` is the single source of truth for the chunker's
    configurable output shape. Chunkers with fixed output set it to
    ``EmptyOptions``; the stage catalog then exposes an empty list
    instead of inventing options that do nothing.
    """

    name: str
    version: str
    options_model: type[BaseModel]

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        options: OptionsInput | None = None,
    ) -> list[Chunk]: ...


def split_text_with_offsets(
    *,
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[tuple[str, int, int]]:
    """Split text and return ``(piece, start, end)`` character offsets.

    This is the offset-aware core of :func:`chunk_text_recursive`,
    extracted so the section-aware chunkers can reuse the exact same
    splitting and offset semantics. The cursor walk is deliberately
    identical to the original implementation: each piece is located
    at or after the previous piece's end, which keeps offsets
    monotonic even when the document repeats the same sentence. When
    the splitter trims whitespace and the piece is not found
    verbatim, the cursor is used as a best-effort start.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    pieces: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in splitter.split_text(text):
        idx = text.find(piece, cursor)
        if idx == -1:
            start = cursor
            end = cursor + len(piece)
        else:
            start = idx
            end = idx + len(piece)
        cursor = end
        pieces.append((piece, start, end))
    return pieces


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
    pairs = split_text_with_offsets(
        text=text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return [
        Chunk(
            id=make_chunk_id(document_id, source_version, ordinal, piece),
            text=piece,
            metadata=metadata,
            parent_id=None,
            source_offset=SourceOffset(start=start, end=end, unit="char"),
        )
        for ordinal, (piece, start, end) in enumerate(pairs)
    ]


__all__ = [
    "Chunk",
    "Chunker",
    "ChunkerInputError",
    "ChunkerOptionError",
    "Document",
    "EmptyDocumentError",
    "OptionsInput",
    "SourceOffset",
    "chunk_text_recursive",
    "make_chunk_id",
    "split_text_with_offsets",
]


def _iter_chunks(chunks: Iterable[Chunk]) -> Iterable[Chunk]:
    """Helper for tests and consumers that want a stable iteration."""
    return list(chunks)
