"""BAAI/bge-base-zh-v1.5 embedder.

BGE-base-zh-v1.5 is a Chinese retrieval model: 768-d, 512 input
tokens, roughly 400 MB of weights. It is the middle point between the
very small bge-small-zh-v1.5 and the heavier bge-m3, which makes it a
good default for a local Chinese knowledge base.

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

BGE zh v1.5 was trained with an optional query instruction. Retrieval
quality improves when the instruction is prepended to short questions,
while documents are embedded as-is; ``embed`` applies that asymmetry
through its ``mode`` argument. cliver-core intentionally leaves
query/document semantics to the application, so the prefix stays here.
"""

from __future__ import annotations

import asyncio

from cliver_core.capabilities import embed as cliver_embed
from cliver_core.local import LocalEmbeddingProvider, local_embed

DIM = 768
MODEL_ID = "BAAI/bge-base-zh-v1.5"
# The instruction recommended by the model card for retrieval queries.
# It is applied only in query mode; document embeddings stay untouched.
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
BATCH_SIZE = 32


class BgeBaseZhEmbedder:
    """BGE-base-zh-v1.5 via cliver-core's local sentence-transformers backend."""

    id = f"{MODEL_ID}@lazy"
    dim = DIM
    max_input_tokens = 512
    supports_query_document_modes = True

    def __init__(self, provider: LocalEmbeddingProvider | None = None) -> None:
        # ``provider`` is injectable so unit tests can supply a fake backend
        # without resolving or downloading weights.
        self._provider = provider or LocalEmbeddingProvider(
            model=MODEL_ID,
            backend="sentence-transformers",
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
        if not texts:
            return []
        if mode == "query":
            texts = [QUERY_INSTRUCTION + text for text in texts]
        return asyncio.run(self._embed(texts))

    def estimate_tokens(self, text: str) -> int:
        # The BERT tokenizer used by this model is close to one token per
        # Chinese character; ASCII text has fewer tokens than characters.
        # A character count is therefore a conservative upper bound, and
        # the value is metadata for the chunk preview, not a hard limit.
        return len(text)
