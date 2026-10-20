"""BAAI/bge-m3 embedder.

BGE-M3 is multilingual (100+ langs), 1024-d, CPU-capable, and can emit
dense, sparse and ColBERT outputs from one forward pass. Only the dense
vector is requested and persisted here; the lexical leg of hybrid
retrieval uses Postgres full-text, so the sparse output is not needed.

Model loading and inference belong to cliver-core's in-process local
provider. The stage owns one long-lived provider (the registries keep one
stage instance per name for the process lifetime), which is how
cliver-core shares a loaded model: it deliberately has no process-global
cache. The model is fetched on the first ``embed`` call, so importing the
package and constructing the stage download nothing.

The concrete HF revision is not resolved at construction time, so ``id``
keeps the ``@lazy`` sentinel; rows in
``rag_chunk_embeddings.embedder_version`` therefore identify the model
family and a future change can fill in the exact revision.
"""

from __future__ import annotations

import asyncio

from cliver_core.capabilities import embed as cliver_embed
from cliver_core.local import LocalEmbeddingProvider, local_embed

DIM = 1024
ID_PREFIX = "BAAI/bge-m3"
BATCH_SIZE = 32


class BgeM3Embedder:
    """BGE-M3 via cliver-core's local FlagEmbedding backend, CPU-capable."""

    id = f"{ID_PREFIX}@lazy"
    dim = DIM
    max_input_tokens = 8192
    supports_query_document_modes = True

    def __init__(self, provider: LocalEmbeddingProvider | None = None) -> None:
        # ``provider`` is injectable so unit tests can supply a fake backend
        # without resolving or downloading weights.
        self._provider = provider or LocalEmbeddingProvider(
            model=ID_PREFIX,
            backend="flag-embedding",
            device="cpu",
            dtype="auto",
            max_length=self.max_input_tokens,
        )
        self._binding = local_embed(
            provider=self._provider,
            dim=DIM,
            normalize=True,
            batch_size=BATCH_SIZE,
        )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        result = await cliver_embed(texts=texts, binding=self._binding)
        return result.vectors

    def embed(self, texts: list[str], *, mode: str = "document") -> list[list[float]]:
        # cliver-core local models expose no query/document semantics. BGE-M3
        # is symmetric, so ``mode`` is accepted for protocol compatibility and
        # does not change the texts sent to the model.
        if not texts:
            return []
        return asyncio.run(self._embed(texts))

    def estimate_tokens(self, text: str) -> int:
        return len(text.split())
