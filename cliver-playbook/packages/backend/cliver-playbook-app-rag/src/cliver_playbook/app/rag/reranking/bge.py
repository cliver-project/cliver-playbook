"""BAAI/bge-reranker-v2-m3 cross-encoder reranker.

The model is loaded lazily on the first ``rerank`` call, mirroring the
BGE-M3 embedder: importing the package and constructing the reranker
must not download weights, and unit tests can assert metadata without a
network round trip.

``compute_score`` returns one relevance score per (query, passage)
pair; with ``normalize=True`` the scores are squashed into [0, 1]. That
range is what ``Settings.rag.score_floor`` is defined on, so the
reranked hits carry these scores rather than the retriever's ranks —
downstream code sees one consistent relevance scale.
"""

from __future__ import annotations

import logging
import threading

from cliver_playbook.app.rag.retrieval.base import Hit

logger = logging.getLogger("cliver_playbook.app.rag.reranking.bge")

MODEL_ID = "BAAI/bge-reranker-v2-m3"


class BgeRerankerV2M3:
    """FlagEmbedding cross-encoder reranker, CPU-capable."""

    name = "bge-reranker-v2-m3"
    # The exact revision is resolved by the model loader; the lazy
    # sentinel documents that the id is not a hallucinated commit hash.
    model_id = f"{MODEL_ID}@lazy"
    produces_relevance_scores = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]

            logger.info("Loading %s (CPU, fp32) — first call downloads the weights", MODEL_ID)
            self._model = FlagReranker(MODEL_ID, use_fp16=False)

    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]:
        if not hits:
            return []
        self._ensure_loaded()
        scores = self._model.compute_score(  # type: ignore[union-attr]
            [(query, hit.text) for hit in hits],
            normalize=True,
        )
        # A single pair comes back as a scalar rather than a list.
        if isinstance(scores, (int, float)):
            scores = [scores]
        ranked = sorted(
            zip(hits, scores, strict=True),
            key=lambda pair: float(pair[1]),
            reverse=True,
        )
        rescored = [hit.model_copy(update={"score": float(score)}) for hit, score in ranked]
        return rescored[:top_k] if top_k is not None else rescored
