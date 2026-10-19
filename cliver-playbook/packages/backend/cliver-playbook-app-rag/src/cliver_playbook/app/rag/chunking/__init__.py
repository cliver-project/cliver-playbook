"""Chunker protocol + four default implementations.

The chunker is the first of the five RAG stages; the public
``get_chunker(name)`` returns one of ``recursive`` / ``markdown`` /
``code`` / ``pdf``. New chunkers register themselves at import via
``chunking.registry.register(name, factory)``.
"""

from __future__ import annotations

from .base import (
    Chunk,
    Chunker,
    ChunkerInputError,
    ChunkerOptionError,
    Document,
    EmptyDocumentError,
    OptionsInput,
    SourceOffset,
    chunk_text_recursive,
    make_chunk_id,
    split_text_with_offsets,
)
from .options import (
    BaseOptions,
    DocxOptions,
    EmptyOptions,
    HtmlOptions,
    SectionOptions,
    describe_options,
)
from .registry import get_chunker, registry

__all__ = [
    "BaseOptions",
    "Chunk",
    "Chunker",
    "ChunkerInputError",
    "ChunkerOptionError",
    "Document",
    "DocxOptions",
    "EmptyDocumentError",
    "EmptyOptions",
    "HtmlOptions",
    "OptionsInput",
    "SectionOptions",
    "SourceOffset",
    "chunk_text_recursive",
    "describe_options",
    "get_chunker",
    "make_chunk_id",
    "registry",
    "split_text_with_offsets",
]
