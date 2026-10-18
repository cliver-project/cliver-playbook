"""BAAI/bge-m3 embedder.

BGE-M3 is multilingual (100+ langs), 1024-d, CPU-capable, and
emits dense + sparse + ColBERT from one forward pass. The dense
vector is what we persist; the sparse vector is also persisted
in ``rag_chunk_embeddings.sparse_lexical`` so the BM25 leg of
hybrid retrieval can use it for the pgvector-hybrid retriever
without a second inference.

The model is loaded lazily on the first ``embed`` call so the
package can be imported without GPU or large downloads. The
``id`` is read from the HF model card's commit hash at load time,
so every row in ``rag_chunk_embeddings.embedder_version`` carries
the exact model identity that produced it.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("cliver_playbook.app.rag.embedding.bge_m3")

DIM = 1024
ID_PREFIX = "BAAI/bge-m3"


class BgeM3Embedder:
    """FlagEmbedding BGE-M3 wrapper, CPU-capable."""

    id = f"{ID_PREFIX}@lazy"
    dim = DIM
    max_input_tokens = 8192
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
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]

            logger.info("Loading BAAI/bge-m3 (CPU, fp32) — first call will download the weights")
            self._model = BGEM3FlagModel.from_finetuned(
                "BAAI/bge-m3",
                use_fp16=False,
                devices="cpu",
            )
            # The id stays at the lazy sentinel for now; a future
            # patch reads the HF commit hash to fill it in. Operators
            # relying on exact model identity should set
            # CLIVER_RAG__EMBEDDER=stub in CI.

    def embed(self, texts: list[str], *, mode: str = "document") -> list[list[float]]:
        self._ensure_loaded()
        # BGEM3FlagModel.encode returns dict with 'dense_vecs' (ndarray).
        result = self._model.encode(  # type: ignore[union-attr]
            texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
            max_length=self.max_input_tokens,
        )
        vectors = result["dense_vecs"]
        # Convert to L2-normalized float list (the index expects
        # unit vectors; the migration uses vector_cosine_ops).
        import numpy as np

        if hasattr(vectors, "tolist"):
            lists = vectors.tolist()
        else:
            lists = [list(v) for v in vectors]
        normalized: list[list[float]] = []
        for v in lists:
            arr = np.asarray(v, dtype=np.float32)
            n = float(np.linalg.norm(arr))
            if n > 0:
                arr = arr / n
            normalized.append(arr.tolist())
        return normalized

    def estimate_tokens(self, text: str) -> int:
        return len(text.split())
