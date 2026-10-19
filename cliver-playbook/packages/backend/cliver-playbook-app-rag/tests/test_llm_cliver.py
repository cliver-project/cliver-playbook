"""The cliver-core generator stage: configuration mapping and the sync seam.

These tests never reach a provider. ``binding()`` builds cliver-core's
dataclass without network I/O, and the generation tests replace
``AgentCore`` with a fake so the adapter contract (prompt, system prompt,
token budget, cleanup, text extraction) is pinned independently of any
vendor API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cliver_playbook.app.rag.llm import cliver as cliver_module
from cliver_playbook.app.rag.llm.cliver import CliverCoreLLM
from cliver_playbook.app.rag.settings import CliverLLMSettings


def _config(**overrides) -> CliverLLMSettings:
    values = {
        "model": "test-model",
        "api_key": "test-key",
        "base_url": "http://model.invalid/v1",
        "params": {"temperature": 0.2},
    }
    values.update(overrides)
    return CliverLLMSettings(**values)


def test_registry_exposes_the_stage() -> None:
    from cliver_playbook.app.rag.llm import get_llm

    assert get_llm("cliver-core").name == "cliver-core"


def test_binding_maps_configuration() -> None:
    llm = CliverCoreLLM(_config(protocol="anthropic", provider_name="example-brand"))

    binding = llm.binding()

    assert binding.model == "test-model"
    assert binding.api_key == "test-key"
    assert binding.base_url == "http://model.invalid/v1"
    assert binding.protocol == "anthropic"
    assert binding.provider_name == "example-brand"
    assert binding.purpose == "llm"
    assert binding.params == {"temperature": 0.2}


def test_generate_runs_cliver_core_and_closes_it(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, bindings) -> None:
            captured["binding"] = bindings.llm

        async def chat(self, prompt: str, *, system_prompt=None, options=None):
            captured.update(prompt=prompt, system=system_prompt, options=options)
            return SimpleNamespace(message=SimpleNamespace(content="grounded answer"))

        async def aclose(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(cliver_module, "AgentCore", FakeAgent)

    answer = CliverCoreLLM(_config()).generate(
        system="system prompt", prompt="grounded prompt", max_tokens=64
    )

    assert answer == "grounded answer"
    assert captured["prompt"] == "grounded prompt"
    assert captured["system"] == "system prompt"
    # The endpoint owns the budget: it wins over anything in params.
    assert captured["options"] == {"max_tokens": 64}
    assert captured["closed"] is True


def test_generate_flattens_text_blocks(monkeypatch) -> None:
    class FakeAgent:
        def __init__(self, bindings) -> None:
            pass

        async def chat(self, prompt: str, *, system_prompt=None, options=None):
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        {"type": "text", "text": "first"},
                        {"type": "image"},
                        {"text": "second"},
                    ]
                )
            )

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(cliver_module, "AgentCore", FakeAgent)

    assert CliverCoreLLM(_config()).generate(system="s", prompt="p") == "first\nsecond"


def test_model_id_follows_the_live_binding() -> None:
    config = _config()
    llm = CliverCoreLLM(config)
    assert llm.model_id == "cliver-core@test-model"

    # The settings section updates the nested object in place while the
    # registry keeps the instance cached; the label must not go stale.
    config.model = "another-model"
    assert llm.model_id == "cliver-core@another-model"

    config.model = ""
    assert llm.model_id == "cliver-core@unconfigured"


def test_unconfigured_model_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError, match="cliver_llm.model"):
        CliverCoreLLM(CliverLLMSettings()).generate(system="s", prompt="p")


def test_missing_endpoint_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError, match="base_url"):
        CliverCoreLLM(CliverLLMSettings(model="test-model")).generate(system="s", prompt="p")
