"""Reranker protocol.

The reranker is the fourth RAG stage: it takes the retriever's candidate
list and reorders (and truncates) it for the generator. It is pure CPU
/ model inference — no database access — so the protocol is synchronous
and the caller runs it in a worker thread.

The ``produces_relevance_scores`` flag states what the returned ``score``
means. A real cross-encoder returns calibrated relevance in [0, 1], which
is the scale ``Settings.rag.score_floor`` is defined on. The noop
implementation passes the retriever's scores through untouched (RRF sums
or cosine similarity, depending on the mode), so a floor expressed in
relevance units must not be applied to its output. Making that explicit
keeps callers from guessing based on the reranker's name.
"""

from __future__ import annotations

from typing import Protocol

from cliver_playbook.app.rag.retrieval.base import Hit


class Reranker(Protocol):
    """The reranker seam.

    Implementations: ``BgeRerankerV2M3`` (BAAI/bge-reranker-v2-m3,
    lazily loaded) and ``NoopReranker`` (identity, for debugging the
    stages around it). New rerankers register themselves at import via
    ``reranking.registry.register(name, factory)``.
    """

    name: str
    model_id: str
    produces_relevance_scores: bool

    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]: ...
