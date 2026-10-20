"""RAG ORM models. Importable without side effects.

The chunker / embedder / retriever / reranker / LLM registries do not
touch the database; only the api/* routers and services/* modules do.
Keeping models importable without side effects means unit tests can
build an in-memory engine and exercise the schema without booting the
process runtime.
"""

from __future__ import annotations

from cliver_playbook.app.rag.models.base import Base
from cliver_playbook.app.rag.models.entities import Chunk, ChunkEmbedding, Document

__all__ = ["Base", "Chunk", "ChunkEmbedding", "Document"]
