"""Offline embedder for tests and for a fresh project with no model
download. Deterministic, hash-based 64-d L2-normalized vectors.

Production code should use ``BgeM3Embedder``; the stub exists so a
test or a developer laptop without internet can still exercise the
upload + index + search flow end to end.
"""

from __future__ import annotations

import hashlib

import numpy as np

DIM = 64
ID = "stub@1.0"


class StubEmbedder:
    """Deterministic, offline, hash-based 64-d embedder.

    The vector is ``RandomState(hash(text)).randn(64)`` L2-normalized.
    Two calls on the same text return the same vector; two calls on
    different texts return different vectors.
    """

    id = ID
    dim = DIM
    max_input_tokens = 8192
    supports_query_document_modes = False

    def embed(self, texts: list[str], *, mode: str = "document") -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:4], "big")
            rng = np.random.RandomState(seed)
            v = rng.randn(self.dim).astype(np.float32)
            n = float(np.linalg.norm(v))
            if n > 0:
                v = v / n
            out.append(v.tolist())
        return out

    def estimate_tokens(self, text: str) -> int:
        # Word count is a poor tokenizer but a stable, dependency-free
        # approximation; the chunker's pre-flight check uses this
        # for the upload preview. A real embedder would use its
        # actual tokenizer.
        return len(text.split())
