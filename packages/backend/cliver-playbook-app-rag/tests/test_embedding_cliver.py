"""The cliver-core embeddings stage: config mapping and the sync seam.

These tests never reach a provider. ``binding()`` builds cliver-core's
dataclass without network I/O, and the embed tests replace
``cliver_core.embed`` with a fake so the adapter's validation and cleanup
contract is pinned independently of any vendor API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cliver_playbook.app.rag.embedding import cliver as cliver_module
from cliver_playbook.app.rag.embedding.cliver import CliverCoreEmbedder
from cliver_playbook.app.rag.settings import CliverEmbedSettings


class FakeBinding:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _config(**overrides) -> CliverEmbedSettings:
    values = {
        "model": "test-embed-model",
        "api_key": "test-key",
        "base_url": "http://model.invalid/v1",
        "path": "/custom/embeddings",
        "dim": 4,
        "params": {"dimensions": 4},
    }
    values.update(overrides)
    return CliverEmbedSettings(**values)


def _fake_vectors(length: int, dim: int = 4) -> SimpleNamespace:
    return SimpleNamespace(vectors=[[0.0] * dim for _ in range(length)])


def test_registry_exposes_the_stage() -> None:
    from cliver_playbook.app.rag.embedding import get_embedder

    stage = get_embedder("cliver-core")
    assert isinstance(stage, CliverCoreEmbedder)
    assert stage.max_input_tokens > 0
    assert stage.supports_query_document_modes is False


def test_binding_maps_configuration() -> None:
    embedder = CliverCoreEmbedder(_config(provider_name="example-brand"))

    binding = embedder.binding()

    assert binding.model == "test-embed-model"
    assert binding.api_key == "test-key"
    assert binding.base_url == "http://model.invalid/v1"
    assert binding.protocol == "openai"
    assert binding.provider_name == "example-brand"
    assert binding.path == "/custom/embeddings"
    assert binding.purpose == "embed"
    assert binding.params == {"dimensions": 4}


def test_id_covers_the_model_and_dimension() -> None:
    assert CliverCoreEmbedder(_config(model="m", dim=8)).id == "cliver-core@m@8"
    assert CliverCoreEmbedder(_config(model="", dim=8)).id == "cliver-core@unconfigured"

    # The column is String(64); long model names get a stable digest.
    long_id = CliverCoreEmbedder(_config(model="x" * 120, dim=8)).id
    assert len(long_id) <= 64
    assert long_id.endswith("@8")


def test_embed_returns_one_vector_per_text_and_closes_the_binding(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_binding = FakeBinding()

    async def fake_embed(*, texts, binding, **options):
        captured.update(texts=texts, binding=binding)
        return _fake_vectors(len(texts))

    monkeypatch.setattr(cliver_module, "cliver_embed", fake_embed)
    embedder = CliverCoreEmbedder(_config())
    monkeypatch.setattr(embedder, "binding", lambda: fake_binding)

    vectors = embedder.embed(["first", "second"], mode="query")

    assert vectors == [[0.0] * 4, [0.0] * 4]
    assert captured["texts"] == ["first", "second"]
    assert captured["binding"] is fake_binding
    assert fake_binding.closed is True


def test_wrong_vector_count_is_a_configuration_error(monkeypatch) -> None:
    async def fake_embed(*, texts, binding, **options):
        return _fake_vectors(len(texts) + 1)

    monkeypatch.setattr(cliver_module, "cliver_embed", fake_embed)
    embedder = CliverCoreEmbedder(_config())
    monkeypatch.setattr(embedder, "binding", FakeBinding)

    with pytest.raises(RuntimeError, match="2 vectors for 1 texts"):
        embedder.embed(["only"])


def test_wrong_vector_size_is_a_configuration_error(monkeypatch) -> None:
    async def fake_embed(*, texts, binding, **options):
        return _fake_vectors(len(texts), dim=3)

    monkeypatch.setattr(cliver_module, "cliver_embed", fake_embed)
    embedder = CliverCoreEmbedder(_config(dim=4))
    monkeypatch.setattr(embedder, "binding", FakeBinding)

    with pytest.raises(RuntimeError, match="rag.cliver_embed.dim is 4"):
        embedder.embed(["only"])


def test_unconfigured_model_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError, match="cliver_embed.model"):
        CliverCoreEmbedder(CliverEmbedSettings()).embed(["text"])


def test_missing_endpoint_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError, match="base_url"):
        CliverCoreEmbedder(CliverEmbedSettings(model="test-model")).embed(["text"])


def test_estimate_tokens_is_a_character_heuristic() -> None:
    embedder = CliverCoreEmbedder(_config())
    assert embedder.estimate_tokens("") == 0
    assert embedder.estimate_tokens("one") == 1
    assert embedder.estimate_tokens("abcdefgh") == 2
