"""Chunker protocol + four default implementations.

The chunker is the first of the five RAG stages; the public
``get_chunker(name)`` returns one of ``recursive`` / ``markdown`` /
``code`` / ``pdf``. New chunkers register themselves at import via
``chunking.registry.register(name, factory)``.
"""

from __future__ import annotations

from cliver_playbook.app.rag.chunking.base import (
    Chunk,
    Chunker,
    Document,
    SourceOffset,
    make_chunk_id,
)
from cliver_playbook.app.rag.chunking.registry import get_chunker, registry

__all__ = [
    "Chunk",
    "Chunker",
    "Document",
    "SourceOffset",
    "get_chunker",
    "make_chunk_id",
    "registry",
]
