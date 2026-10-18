"""Embedder tests: registry, stub determinism, BGE-M3 metadata."""

from __future__ import annotations

import math

from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.embedding.registry import registry


def test_registry_has_bge_m3_and_stub() -> None:
    names = registry.names()
    assert "bge-m3" in names
    assert "stub" in names


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


def test_unknown_embedder_raises() -> None:
    import pytest

    with pytest.raises(KeyError):
        get_embedder("no-such-embedder")
