"""BAAI/bge-reranker-v2-m3 cross-encoder reranker.

Model loading and inference belong to cliver-core's in-process local
provider, mirroring the BGE-M3 embedder. The stage owns one long-lived
provider (the registries keep one stage instance per name for the process
lifetime), which is how cliver-core shares a loaded model: it
deliberately has no process-global cache. The model is fetched on the
first ``rerank`` call, so importing the package and constructing the
reranker download nothing.

cliver-core's local rerank provider returns raw cross-encoder scores and
optionally applies a stable sigmoid; ``normalize=True`` yields [0, 1],
the scale ``Settings.rag.score_floor`` is defined on. This stage keeps
its own sort and ``top_k`` slice so its ranking contract does not depend
on provider ordering.
"""

from __future__ import annotations

import asyncio

from cliver_core.capabilities import rerank as cliver_rerank
from cliver_core.local import LocalRerankProvider, local_rerank
from cliver_core.provider import RerankItem

from cliver_playbook.app.rag.retrieval.base import Hit

MODEL_ID = "BAAI/bge-reranker-v2-m3"
BATCH_SIZE = 32


class BgeRerankerV2M3:
    """BGE reranker via cliver-core's local FlagEmbedding backend, CPU-capable."""

    name = "bge-reranker-v2-m3"
    # The exact revision is resolved by the model loader; the lazy
    # sentinel documents that the id is not a hallucinated commit hash.
    model_id = f"{MODEL_ID}@lazy"
    produces_relevance_scores = True

    def __init__(self, provider: LocalRerankProvider | None = None) -> None:
        # ``provider`` is injectable so unit tests can supply a fake backend
        # without resolving or downloading weights.
        self._provider = provider or LocalRerankProvider(
            model=MODEL_ID,
            backend="flag-embedding",
            device="cpu",
            dtype="auto",
        )
        self._binding = local_rerank(
            provider=self._provider,
            normalize=True,
            batch_size=BATCH_SIZE,
        )

    async def _rerank(self, query: str, documents: list[str]) -> list[RerankItem]:
        return await cliver_rerank(
            query=query,
            documents=documents,
            binding=self._binding,
        )

    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]:
        if not hits:
            return []
        items = asyncio.run(self._rerank(query, [hit.text for hit in hits]))
        rescored = [
            hits[item.index].model_copy(update={"score": float(item.relevance_score)})
            for item in items
        ]
        rescored.sort(key=lambda hit: hit.score, reverse=True)
        return rescored[:top_k] if top_k is not None else rescored
