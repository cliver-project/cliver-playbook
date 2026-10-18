"""Default chunker: langchain's RecursiveCharacterTextSplitter."""

from __future__ import annotations

from cliver_playbook.app.rag.chunking.base import (
    Chunk,
    Document,
    chunk_text_recursive,
)

VERSION = "1.0.0"


class RecursiveChunker:
    """The default chunker.

    Splits text recursively on the priority list ``\\n\\n``, ``\\n``,
    `` ``, ``.`` — never mid-word. Content-hash IDs make re-indexing
    idempotent. No header awareness; use ``MarkdownChunker`` for that.
    """

    name = "recursive"
    version = VERSION

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> list[Chunk]:
        text = doc.raw if isinstance(doc.raw, str) else doc.raw.decode("utf-8")
        return chunk_text_recursive(
            text=text,
            document_id=doc.id,
            source_version=doc.source_version,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            metadata=dict(doc.metadata),
        )
