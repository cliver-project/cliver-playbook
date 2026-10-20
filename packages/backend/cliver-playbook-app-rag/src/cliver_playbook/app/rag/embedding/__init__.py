"""Embedder protocol + stub, local BGE and cliver-core implementations.

The embedder is the second of the five RAG stages. ``get_embedder(name)``
returns one of ``stub`` (offline default, deterministic, 64-d),
``bge-m3`` or ``bge-base-zh-v1.5`` (CPU-capable local models loaded
lazily through cliver-core's in-process providers), or ``cliver-core``
(remote purpose binding).
"""

from __future__ import annotations

from cliver_playbook.app.rag.embedding.base import Embedder, Embedding
from cliver_playbook.app.rag.embedding.registry import get_embedder, registry

__all__ = ["Embedder", "Embedding", "get_embedder", "registry"]
