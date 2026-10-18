"""Reranker protocol + BGE cross-encoder and noop implementations.

The reranker is the fourth of the five RAG stages. ``get_reranker(name)``
returns one of ``bge-reranker-v2-m3`` (production default, lazily
loaded) or ``noop`` (identity, offline-safe).
"""

from __future__ import annotations

from cliver_playbook.app.rag.reranking.base import Reranker
from cliver_playbook.app.rag.reranking.registry import get_reranker, registry

__all__ = ["Reranker", "get_reranker", "registry"]
