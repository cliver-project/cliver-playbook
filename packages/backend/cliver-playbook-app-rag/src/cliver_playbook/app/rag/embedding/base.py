"""Embedder protocol + Embedding wire shape."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class Embedding(BaseModel):
    """One embedding vector with provenance metadata.

    The ``vector`` is the raw float list. ``model_id`` is the
    embedder's stable identifier (e.g. ``BAAI/bge-m3@<commit>`` or
    ``stub@1.0``); ``dim`` is the dimensionality. ``mode`` records
    whether the embedder was called in ``query`` or ``document``
    mode (matters when the embedder is asymmetric).
    """

    vector: list[float]
    model_id: str
    dim: int
    mode: Literal["query", "document", "unspecified"] = "unspecified"


class Embedder(Protocol):
    """The embedder seam.

    Implementations: ``StubEmbedder`` (offline default, deterministic
    hash-based 64-d), ``BgeM3Embedder`` (BGE-M3, 1024-d, CPU-capable
    through cliver-core's local FlagEmbedding backend),
    ``BgeBaseZhEmbedder`` (BGE-base-zh-v1.5, 768-d, CPU-capable through
    cliver-core's local sentence-transformers backend), and
    ``CliverCoreEmbedder`` (remote binding). New embedders register
    themselves at import via
    ``embedding.registry.register(name, factory)``.
    """

    id: str
    dim: int
    max_input_tokens: int
    supports_query_document_modes: bool

    def embed(
        self, texts: list[str], *, mode: Literal["query", "document", "unspecified"] = "document"
    ) -> list[list[float]]: ...

    def estimate_tokens(self, text: str) -> int: ...
