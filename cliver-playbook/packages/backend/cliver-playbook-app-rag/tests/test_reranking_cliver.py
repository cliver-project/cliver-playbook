"""The cliver-core rerank stage: config mapping and the sync seam.

These tests never reach a provider. ``binding()`` builds cliver-core's
dataclass without network I/O, and the rerank tests replace
``cliver_core.rerank`` with a fake so index mapping, ordering, truncation
and cleanup are pinned independently of any vendor API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cliver_playbook.app.rag.reranking import cliver as cliver_module
from cliver_playbook.app.rag.reranking.cliver import CliverCoreReranker
from cliver_playbook.app.rag.retrieval.base import Hit
from cliver_playbook.app.rag.settings import CliverRerankSettings


class FakeBinding:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _config(**overrides) -> CliverRerankSettings:
    values = {
        "model": "test-rerank-model",
        "api_key": "test-key",
        "base_url": "http://model.invalid/v1",
        "path": "/custom/rerank",
        "params": {"top_n": 5},
    }
    values.update(overrides)
    return CliverRerankSettings(**values)


def _hits() -> list[Hit]:
    return [
        Hit(
            chunk_id=chr(ord("a") + i),
            document_id="d",
            ordinal=i,
            text=f"text {i}",
            score=0.1,
            metadata={},
        )
        for i in range(3)
    ]


def test_registry_exposes_the_stage() -> None:
    from cliver_playbook.app.rag.reranking import get_reranker

    stage = get_reranker("cliver-core")
    assert isinstance(stage, CliverCoreReranker)
    assert stage.produces_relevance_scores is True


def test_binding_maps_configuration() -> None:
    reranker = CliverCoreReranker(_config(provider_name="example-brand"))

    binding = reranker.binding()

    assert binding.model == "test-rerank-model"
    assert binding.api_key == "test-key"
    assert binding.base_url == "http://model.invalid/v1"
    assert binding.protocol == "openai"
    assert binding.provider_name == "example-brand"
    assert binding.path == "/custom/rerank"
    assert binding.purpose == "rerank"
    assert binding.params == {"top_n": 5}


def test_model_id_follows_the_live_binding() -> None:
    config = _config()
    reranker = CliverCoreReranker(config)
    assert reranker.model_id == "cliver-core@test-rerank-model"

    config.model = "another-model"
    assert reranker.model_id == "cliver-core@another-model"

    config.model = ""
    assert reranker.model_id == "cliver-core@unconfigured"


def test_rerank_maps_indices_sorts_and_closes_the_binding(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_binding = FakeBinding()

    async def fake_rerank(*, query, documents, binding, top_k=None):
        captured.update(query=query, documents=documents, binding=binding, top_k=top_k)
        return [
            SimpleNamespace(index=2, relevance_score=0.4),
            SimpleNamespace(index=0, relevance_score=0.9),
            SimpleNamespace(index=1, relevance_score=0.6),
        ]

    monkeypatch.setattr(cliver_module, "cliver_rerank", fake_rerank)
    reranker = CliverCoreReranker(_config())
    monkeypatch.setattr(reranker, "binding", lambda: fake_binding)

    out = reranker.rerank("what?", _hits(), top_k=2)

    assert [hit.chunk_id for hit in out] == ["a", "b"]
    assert [hit.score for hit in out] == [0.9, 0.6]
    assert captured["query"] == "what?"
    assert captured["documents"] == ["text 0", "text 1", "text 2"]
    assert captured["top_k"] == 2
    assert captured["binding"] is fake_binding
    assert fake_binding.closed is True


def test_out_of_range_indices_are_ignored(monkeypatch) -> None:
    async def fake_rerank(*, query, documents, binding, top_k=None):
        return [
            SimpleNamespace(index=9, relevance_score=0.99),
            SimpleNamespace(index=1, relevance_score=0.5),
        ]

    monkeypatch.setattr(cliver_module, "cliver_rerank", fake_rerank)
    reranker = CliverCoreReranker(_config())
    monkeypatch.setattr(reranker, "binding", FakeBinding)

    out = reranker.rerank("q", _hits())

    assert [hit.chunk_id for hit in out] == ["b"]
    assert out[0].score == 0.5


def test_empty_hits_skip_the_provider(monkeypatch) -> None:
    async def fail(*args, **kwargs):  # pragma: no cover - called only on a bug
        raise AssertionError("the provider must not be called for an empty hit list")

    monkeypatch.setattr(cliver_module, "cliver_rerank", fail)

    assert CliverCoreReranker(_config()).rerank("q", []) == []


def test_unconfigured_model_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError, match="cliver_rerank.model"):
        CliverCoreReranker(CliverRerankSettings()).rerank("q", _hits())


def test_missing_endpoint_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError, match="base_url"):
        CliverCoreReranker(CliverRerankSettings(model="test-model")).rerank("q", _hits())
