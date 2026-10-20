"""Identity reranker: keep the retriever's order, optionally truncate.

Useful when debugging the other stages (it removes the reranker from the
equation) and as the offline-safe option. It preserves each hit's score
exactly and therefore does not claim relevance-score semantics.
"""

from __future__ import annotations

from cliver_playbook.app.rag.retrieval.base import Hit


class NoopReranker:
    """Pass-through reranker."""

    name = "noop"
    model_id = "noop@1.0"
    produces_relevance_scores = False

    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]:
        return hits[:top_k] if top_k is not None else hits
