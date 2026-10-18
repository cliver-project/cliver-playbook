"""BAAI/bge-base-zh-v1.5 embedder.

BGE-base-zh-v1.5 is a Chinese retrieval model: 768-d, 512 input
tokens, roughly 400 MB of weights. It is the middle point between the
very small bge-small-zh-v1.5 and the heavier bge-m3, which makes it a
good default for a local Chinese knowledge base.

The model is loaded lazily on the first ``embed`` call so importing the
package downloads nothing. The concrete HF revision is not resolved at
load time, so ``id`` keeps the ``@lazy`` sentinel; rows in
``rag_chunk_embeddings.embedder_version`` therefore identify the model
family and a future change can fill in the exact revision.

BGE zh v1.5 was trained with an optional query instruction. Retrieval
quality improves when the instruction is prepended to short questions,
while documents are embedded as-is; ``embed`` applies that asymmetry
through its ``mode`` argument.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("cliver_playbook.app.rag.embedding.bge_base_zh")

DIM = 768
MODEL_ID = "BAAI/bge-base-zh-v1.5"
# The instruction recommended by the model card for retrieval queries.
# It is applied only in query mode; document embeddings stay untouched.
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class BgeBaseZhEmbedder:
    """SentenceTransformer wrapper for BGE-base-zh-v1.5, CPU-capable."""

    id = f"{MODEL_ID}@lazy"
    dim = DIM
    max_input_tokens = 512
    supports_query_document_modes = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer

            logger.info(
                "Loading %s (CPU) — first call will download the weights",
                MODEL_ID,
            )
            self._model = SentenceTransformer(MODEL_ID, device="cpu")

    def embed(self, texts: list[str], *, mode: str = "document") -> list[list[float]]:
        self._ensure_loaded()
        if mode == "query":
            texts = [QUERY_INSTRUCTION + text for text in texts]
        vectors = self._model.encode(  # type: ignore[union-attr]
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=32,
            show_progress_bar=False,
        )
        # The encoder already normalizes, but the index contract is that
        # every stored vector is unit length. Re-normalizing is cheap and
        # keeps a mocked or alternative backend from violating it.
        import numpy as np

        normalized: list[list[float]] = []
        for vector in vectors:
            arr = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                arr = arr / norm
            normalized.append(arr.tolist())
        return normalized

    def estimate_tokens(self, text: str) -> int:
        # The BERT tokenizer used by this model is close to one token per
        # Chinese character; ASCII text has fewer tokens than characters.
        # A character count is therefore a conservative upper bound, and
        # the value is metadata for the chunk preview, not a hard limit.
        return len(text)
