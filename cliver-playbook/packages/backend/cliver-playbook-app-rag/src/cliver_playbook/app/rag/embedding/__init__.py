"""Embedder protocol + stub and BGE-M3 implementations.

The embedder is the second of the five RAG stages. ``get_embedder(name)``
returns one of ``stub`` (offline default, deterministic, 64-d) or
``bge-m3`` (BAAI/bge-m3, 1024-d, CPU-capable, lazily loaded).
"""

from __future__ import annotations

from cliver_playbook.app.rag.embedding.base import Embedder, Embedding
from cliver_playbook.app.rag.embedding.registry import get_embedder, registry

__all__ = ["Embedder", "Embedding", "get_embedder", "registry"]
