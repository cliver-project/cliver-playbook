"""BAAI/bge-m3 embedder.

BGE-M3 is multilingual (100+ langs), 1024-d, CPU-capable, and can emit
dense, sparse and ColBERT outputs from one forward pass. Only the dense
vector is requested and persisted here; the lexical leg of hybrid
retrieval uses Postgres full-text, so the sparse output is not needed.

The model is loaded lazily on the first ``embed`` call so importing the
package downloads nothing. The concrete HF revision is not resolved at
load time, so ``id`` keeps the ``@lazy`` sentinel; rows in
``rag_chunk_embeddings.embedder_version`` therefore identify the model
family and a future change can fill in the exact revision.
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

            # FlagEmbedding 1.4.x aliases BGEM3FlagModel to M3Embedder, whose
            # public constructor takes the model path directly. The older
            # FlagAutoModel-style ``from_finetuned`` classmethod is not part
            # of this class; calling it raises AttributeError at first use.
            logger.info("Loading BAAI/bge-m3 (CPU, fp32) — first call will download the weights")
            self._model = BGEM3FlagModel(
                "BAAI/bge-m3",
                use_fp16=False,
                devices="cpu",
            )

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
