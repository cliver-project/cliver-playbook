"""Uniform registry contract across the model-backed stages.

Each of these registries memoizes one instance per name. A model-backed
implementation keeps its lazy-load lock and loaded weights on the
instance, so returning a fresh wrapper per lookup would reload the model
on every request; the stateless retriever shares the same contract to
keep the seam uniform. (The chunker registry is deliberately not in
this set: chunkers are pure functions with no per-instance state.)
"""

from __future__ import annotations

import pytest

from cliver_playbook.app.rag.embedding.registry import registry as embedder_registry
from cliver_playbook.app.rag.llm.registry import registry as llm_registry
from cliver_playbook.app.rag.reranking.registry import registry as reranker_registry
from cliver_playbook.app.rag.retrieval.registry import registry as retriever_registry

_REGISTRIES = [
    pytest.param(embedder_registry, "stub", id="embedders"),
    pytest.param(retriever_registry, "bm25-only", id="retrievers"),
    pytest.param(reranker_registry, "noop", id="rerankers"),
    pytest.param(llm_registry, "stub", id="llms"),
]


@pytest.mark.parametrize(("registry", "name"), _REGISTRIES)
def test_registry_memoizes_one_instance_per_name(registry, name: str) -> None:
    first = registry.get(name)
    second = registry.get(name)
    assert first is second


@pytest.mark.parametrize(("registry", "name"), _REGISTRIES)
def test_registry_rejects_duplicate_registration(registry, name: str) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register(name, registry.get)
