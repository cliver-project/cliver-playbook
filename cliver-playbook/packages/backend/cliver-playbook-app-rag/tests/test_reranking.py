"""Reranker registry and the noop implementation.

The BGE reranker is asserted at the metadata level only: calling it
would download model weights, which unit tests must not do. Its scoring
path is exercised in the live smoke run.
"""

from __future__ import annotations

import pytest

from cliver_playbook.app.rag.reranking import get_reranker
from cliver_playbook.app.rag.reranking.registry import registry
from cliver_playbook.app.rag.retrieval.base import Hit


def _hits(scores: list[float]) -> list[Hit]:
    return [
        Hit(
            chunk_id=chr(ord("a") + i),
            document_id="d",
            ordinal=i,
            text=f"text {i}",
            score=score,
            metadata={},
        )
        for i, score in enumerate(scores)
    ]


def test_registry_lists_bge_and_noop() -> None:
    assert {"bge-reranker-v2-m3", "noop"} <= registry.names()


def test_unknown_reranker_raises() -> None:
    with pytest.raises(KeyError, match="unknown reranker"):
        get_reranker("does-not-exist")


def test_noop_preserves_order_and_scores() -> None:
    hits = _hits([0.9, 0.5])
    out = get_reranker("noop").rerank("q", hits)
    assert [hit.chunk_id for hit in out] == ["a", "b"]
    assert [hit.score for hit in out] == [0.9, 0.5]


def test_noop_top_k_truncates() -> None:
    hits = _hits([1.0 - i * 0.1 for i in range(10)])
    out = get_reranker("noop").rerank("q", hits, top_k=3)
    assert [hit.chunk_id for hit in out] == ["a", "b", "c"]


def test_noop_empty_input() -> None:
    assert get_reranker("noop").rerank("q", []) == []


def test_bge_reranker_metadata_without_loading_the_model() -> None:
    reranker = get_reranker("bge-reranker-v2-m3")
    assert reranker.name == "bge-reranker-v2-m3"
    assert "bge-reranker" in reranker.model_id
    assert reranker.produces_relevance_scores is True
    # No weights have been touched by constructing the reranker.
    assert reranker._model is None


def test_noop_does_not_claim_relevance_scores() -> None:
    # The chat endpoint applies score_floor only on a scale that means
    # something; noop passes the retriever's scores through untouched.
    assert get_reranker("noop").produces_relevance_scores is False
