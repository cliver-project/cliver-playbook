"""Retriever protocol + pgvector-hybrid and bm25-only implementations.

The retriever is the third of the five RAG stages. ``get_retriever(name)``
returns one of ``pgvector-hybrid`` (production default: pgvector cosine
plus Postgres full-text, reciprocal-rank-fused) or ``bm25-only``
(offline / SQLite fallback that ranks the chunk table in Python).
"""

from __future__ import annotations

from cliver_playbook.app.rag.retrieval.base import Hit, Query, Retriever
from cliver_playbook.app.rag.retrieval.registry import get_retriever, registry

__all__ = ["Hit", "Query", "Retriever", "get_retriever", "registry"]
