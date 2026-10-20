"""Reranker registry, the noop implementation, and the local BGE stage.

The BGE reranker delegates model loading and inference to cliver-core's
in-process local provider. Its test injects a fake cliver-core backend, so
the scoring path runs without resolving a Hugging Face repository or
downloading weights.
"""

from __future__ import annotations

import pytest
from cliver_core.local import LoadedRerank, LoadSpec, LocalRerankProvider

from cliver_playbook.app.rag.reranking import get_reranker
from cliver_playbook.app.rag.reranking.bge import BgeRerankerV2M3
from cliver_playbook.app.rag.reranking.registry import registry
from cliver_playbook.app.rag.retrieval.base import Hit


class _FakeRerankBackend:
    """A cliver-core rerank backend returning fixed raw (logit) scores."""

    name = "fake-rerank"

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.spec: LoadSpec | None = None
        self.pairs: list[tuple[str, str]] = []

    def load_rerank(self, spec: LoadSpec) -> LoadedRerank:
        self.spec = spec
        return LoadedRerank(
            handle=object(),
            resolved_model=spec.model,
            revision=None,
            device="cpu",
            dtype="float32",
            max_length=spec.max_length,
        )

    def score(
        self, loaded: LoadedRerank, pairs: list[tuple[str, str]], *, batch_size: int
    ) -> list[float]:
        self.pairs.extend(pairs)
        return self.scores[: len(pairs)]

    def unload_rerank(self, loaded: LoadedRerank) -> None:
        pass


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
    assert {"bge-reranker-v2-m3", "noop", "cliver-core"} <= registry.names()


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
    # Constructing the stage must not load or download the model; the
    # cliver-core provider defers that to the first rerank call.
    info = reranker._provider.info()
    assert info.model == "BAAI/bge-reranker-v2-m3"
    assert info.backend == "flag-embedding"
    assert info.loaded is False


def test_noop_does_not_claim_relevance_scores() -> None:
    # The chat endpoint applies score_floor only on a scale that means
    # something; noop passes the retriever's scores through untouched.
    assert get_reranker("noop").produces_relevance_scores is False


def test_bge_reranker_scores_through_cliver_core_local_rerank() -> None:
    backend = _FakeRerankBackend([-1.0, 0.0, 1.0])
    provider = LocalRerankProvider(model="BAAI/bge-reranker-v2-m3", backend=backend)
    reranker = BgeRerankerV2M3(provider=provider)

    out = reranker.rerank("q", _hits([0.9, 0.8, 0.7]))

    assert backend.spec is not None
    assert backend.spec.model == "BAAI/bge-reranker-v2-m3"
    assert backend.pairs == [("q", "text 0"), ("q", "text 1"), ("q", "text 2")]
    # Cross-encoder scores win over the retriever's order; normalize=True
    # turns the raw logits into the [0, 1] scale score_floor is defined on.
    assert [hit.chunk_id for hit in out] == ["c", "b", "a"]
    assert [hit.score for hit in out] == pytest.approx([0.7310586, 0.5, 0.2689414])


def test_bge_reranker_applies_top_k_after_ranking() -> None:
    backend = _FakeRerankBackend([-1.0, 0.0, 1.0])
    provider = LocalRerankProvider(model="BAAI/bge-reranker-v2-m3", backend=backend)
    reranker = BgeRerankerV2M3(provider=provider)

    out = reranker.rerank("q", _hits([0.9, 0.8, 0.7]), top_k=2)

    assert [hit.chunk_id for hit in out] == ["c", "b"]


def test_bge_reranker_empty_input_does_not_load_the_model() -> None:
    backend = _FakeRerankBackend([])
    provider = LocalRerankProvider(model="BAAI/bge-reranker-v2-m3", backend=backend)
    reranker = BgeRerankerV2M3(provider=provider)

    assert reranker.rerank("q", []) == []
    assert backend.spec is None
    assert provider.info().loaded is False
