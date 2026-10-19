"""Embedder tests: registry, stub determinism, BGE-M3 metadata."""

from __future__ import annotations

import math

from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.embedding.registry import registry


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
    norm = math.sqrt(sum(x * x for x in a))
    assert abs(norm - 1.0) < 1e-5
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
    # Don't run the actual model in unit tests; only check metadata
    assert e.dim == 1024
    assert e.supports_query_document_modes is True
    assert e.id.startswith("BAAI/bge-m3@") or e.id.startswith("bge-m3@")


def test_bge_m3_loads_through_the_public_constructor(monkeypatch) -> None:
    """FlagEmbedding 1.4.x has no ``BGEM3FlagModel.from_finetuned``.

    The loader must call the public constructor with the model path; a
    classmethod that does not exist would only fail at the first real
    use (after a download decision), so this test pins the call shape
    with a fake module instead of downloading weights.
    """
    import sys
    import types

    calls: list[tuple[tuple, dict]] = []

    class _FakeModel:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def encode(self, texts, **kwargs):
            return {"dense_vecs": [[3.0, 4.0] for _ in texts]}

    monkeypatch.setitem(
        sys.modules, "FlagEmbedding", types.SimpleNamespace(BGEM3FlagModel=_FakeModel)
    )

    from cliver_playbook.app.rag.embedding.bge_m3 import BgeM3Embedder

    embedder = BgeM3Embedder()
    vectors = embedder.embed(["hello"], mode="document")

    assert calls and calls[0][0] == ("BAAI/bge-m3",)
    assert calls[0][1] == {"use_fp16": False, "devices": "cpu"}
    # The returned vector is L2-normalized (3-4-5 triangle → 0.6/0.8);
    # the model runs in float32, so compare with a tolerance.
    import pytest

    assert vectors[0] == pytest.approx([0.6, 0.8])


def test_bge_base_zh_metadata_and_query_instruction(monkeypatch) -> None:
    """BGE-base-zh-v1.5 loads lazily and prefixes queries only.

    The real model is not downloaded: a fake ``sentence_transformers``
    module pins the constructor and encode call shapes. The query
    instruction is the asymmetry the model card recommends, so it must
    not leak into document embeddings.
    """
    import sys
    import types

    import numpy as np

    init_calls: list[tuple[tuple, dict]] = []
    encode_calls: list[tuple[tuple, dict]] = []

    class _FakeModel:
        def __init__(self, *args, **kwargs):
            init_calls.append((args, kwargs))

        def encode(self, texts, **kwargs):
            encode_calls.append((tuple(texts), kwargs))
            return np.asarray([[3.0, 4.0] for _ in texts])

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=_FakeModel),
    )

    from cliver_playbook.app.rag.embedding.bge_base_zh import (
        QUERY_INSTRUCTION,
        BgeBaseZhEmbedder,
    )

    embedder = BgeBaseZhEmbedder()
    assert embedder.dim == 768
    assert embedder.max_input_tokens == 512
    assert embedder.id.startswith("BAAI/bge-base-zh-v1.5@")

    document_vectors = embedder.embed(["政策正文"], mode="document")
    query_vectors = embedder.embed(["政策如何规定？"], mode="query")

    assert init_calls == [(("BAAI/bge-base-zh-v1.5",), {"device": "cpu"})]
    assert encode_calls[0][0] == ("政策正文",)
    assert encode_calls[1][0] == (QUERY_INSTRUCTION + "政策如何规定？",)
    assert encode_calls[0][1]["normalize_embeddings"] is True
    assert encode_calls[0][1]["show_progress_bar"] is False

    import pytest

    assert document_vectors[0] == pytest.approx([0.6, 0.8])
    assert query_vectors[0] == pytest.approx([0.6, 0.8])


def test_unknown_embedder_raises() -> None:
    import pytest

    with pytest.raises(KeyError):
        get_embedder("no-such-embedder")
