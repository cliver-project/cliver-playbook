"""Embedder tests: registry, stub determinism, and the local BGE stages.

The BGE stages delegate model loading and inference to cliver-core's
in-process local providers. These tests inject a fake cliver-core backend,
so they exercise the real provider, binding and result plumbing without
resolving a Hugging Face repository or downloading weights.
"""

from __future__ import annotations

import math

import pytest
from cliver_core.local import LoadedEmbedding, LoadSpec, LocalEmbeddingProvider

from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.embedding.bge_base_zh import (
    QUERY_INSTRUCTION,
    BgeBaseZhEmbedder,
)
from cliver_playbook.app.rag.embedding.bge_m3 import BgeM3Embedder
from cliver_playbook.app.rag.embedding.registry import registry


class _FakeEmbeddingBackend:
    """A cliver-core backend returning a fixed 3-4-5 vector, with no model."""

    name = "fake-embedding"

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.spec: LoadSpec | None = None
        self.batches: list[tuple[list[str], int]] = []

    def load_embedding(self, spec: LoadSpec) -> LoadedEmbedding:
        self.spec = spec
        return LoadedEmbedding(
            handle=object(),
            resolved_model=spec.model,
            revision=None,
            device="cpu",
            dtype="float32",
            dim=self.dim,
            max_length=spec.max_length,
        )

    def embed(
        self, loaded: LoadedEmbedding, texts: list[str], *, batch_size: int
    ) -> list[list[float]]:
        self.batches.append((list(texts), batch_size))
        raw = [3.0, 4.0] + [0.0] * (self.dim - 2)
        return [list(raw) for _ in texts]

    def unload_embedding(self, loaded: LoadedEmbedding) -> None:
        pass


def _assert_unit_norm(vector: list[float]) -> None:
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)


def test_registry_has_bge_m3_and_stub() -> None:
    names = registry.names()
    assert "bge-m3" in names
    assert "bge-base-zh-v1.5" in names
    assert "stub" in names
    assert "cliver-core" in names


def test_stub_embedder_is_deterministic_unit_norm() -> None:
    e = get_embedder("stub")
    a = e.embed(["hello world"], mode="document")[0]
    b = e.embed(["hello world"], mode="document")[0]
    assert a == b
    _assert_unit_norm(a)
    assert e.dim == 64
    assert "stub" in e.id


def test_stub_embedder_different_text_yields_different_vector() -> None:
    e = get_embedder("stub")
    a = e.embed(["alpha"], mode="document")[0]
    b = e.embed(["beta"], mode="document")[0]
    assert a != b


def test_stub_estimate_tokens_is_word_count() -> None:
    e = get_embedder("stub")
    assert e.estimate_tokens("hello world") == 2
    assert e.estimate_tokens("one") == 1
    assert e.estimate_tokens("") == 0


def test_bge_m3_embedder_metadata() -> None:
    e = get_embedder("bge-m3")
    # Constructing the stage must not load or download the model; the
    # cliver-core provider defers that to the first embed call.
    assert e.dim == 1024
    assert e.max_input_tokens == 8192
    assert e.supports_query_document_modes is True
    assert e.id.startswith("BAAI/bge-m3@")
    info = e._provider.info()
    assert info.model == "BAAI/bge-m3"
    assert info.backend == "flag-embedding"
    assert info.max_length == 8192
    assert info.loaded is False


def test_bge_base_zh_embedder_metadata() -> None:
    e = get_embedder("bge-base-zh-v1.5")
    assert e.dim == 768
    assert e.max_input_tokens == 512
    assert e.supports_query_document_modes is True
    assert e.id.startswith("BAAI/bge-base-zh-v1.5@")
    info = e._provider.info()
    assert info.model == "BAAI/bge-base-zh-v1.5"
    assert info.backend == "sentence-transformers"
    assert info.max_length == 512
    assert info.loaded is False


def test_bge_m3_delegates_to_cliver_core_local_embed() -> None:
    backend = _FakeEmbeddingBackend(1024)
    provider = LocalEmbeddingProvider(model="BAAI/bge-m3", backend=backend)
    embedder = BgeM3Embedder(provider=provider)

    vectors = embedder.embed(["hello", "world"], mode="document")

    assert backend.spec is not None
    assert backend.spec.model == "BAAI/bge-m3"
    assert backend.batches == [(["hello", "world"], 32)]
    assert len(vectors) == 2
    assert vectors[0] == pytest.approx([0.6, 0.8] + [0.0] * 1022)
    _assert_unit_norm(vectors[0])
    _assert_unit_norm(vectors[1])

    # Empty input is answered without touching the model.
    assert embedder.embed([], mode="query") == []
    assert len(backend.batches) == 1


def test_bge_base_zh_delegates_to_cliver_core_and_prefixes_queries_only() -> None:
    backend = _FakeEmbeddingBackend(768)
    provider = LocalEmbeddingProvider(model="BAAI/bge-base-zh-v1.5", backend=backend)
    embedder = BgeBaseZhEmbedder(provider=provider)

    assert embedder.dim == 768
    assert embedder.max_input_tokens == 512
    assert embedder.id.startswith("BAAI/bge-base-zh-v1.5@")

    document_vectors = embedder.embed(["政策正文"], mode="document")
    query_vectors = embedder.embed(["政策如何规定？"], mode="query")

    assert backend.spec is not None
    assert backend.spec.model == "BAAI/bge-base-zh-v1.5"
    assert [batch[0] for batch in backend.batches] == [
        ["政策正文"],
        [QUERY_INSTRUCTION + "政策如何规定？"],
    ]
    assert document_vectors[0] == pytest.approx([0.6, 0.8] + [0.0] * 766)
    assert query_vectors[0] == pytest.approx([0.6, 0.8] + [0.0] * 766)
    _assert_unit_norm(document_vectors[0])
    _assert_unit_norm(query_vectors[0])


def test_unknown_embedder_raises() -> None:
    with pytest.raises(KeyError):
        get_embedder("no-such-embedder")
