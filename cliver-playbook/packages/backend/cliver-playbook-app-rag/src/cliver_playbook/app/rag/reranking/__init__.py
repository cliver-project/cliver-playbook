"""Reranker protocol + BGE cross-encoder, noop and cliver-core implementations.

The reranker is the fourth of the five RAG stages. ``get_reranker(name)``
returns one of ``bge-reranker-v2-m3`` (production default, loaded lazily
through cliver-core's in-process provider), ``noop`` (identity,
offline-safe), or ``cliver-core`` (remote purpose binding).
"""

from __future__ import annotations

from cliver_playbook.app.rag.reranking.base import Reranker
from cliver_playbook.app.rag.reranking.registry import get_reranker, registry

__all__ = ["Reranker", "get_reranker", "registry"]
