"""Default chunker: langchain's RecursiveCharacterTextSplitter."""

from __future__ import annotations

from .base import (
    Chunk,
    Document,
    OptionsInput,
    chunk_text_recursive,
)
from .options import EmptyOptions

VERSION = "1.0.0"


class RecursiveChunker:
    """The default chunker.

    Splits text recursively on the priority list ``\\n\\n``, ``\\n``,
    `` ``, ``.`` — never mid-word. Content-hash IDs make re-indexing
    idempotent. No header awareness; use ``MarkdownChunker`` for that.
    """

    name = "recursive"
    version = VERSION
    options_model = EmptyOptions

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        options: OptionsInput | None = None,
    ) -> list[Chunk]:
        del options
        text = doc.raw if isinstance(doc.raw, str) else doc.raw.decode("utf-8")
        return chunk_text_recursive(
            text=text,
            document_id=doc.id,
            source_version=doc.source_version,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            metadata=dict(doc.metadata),
        )
