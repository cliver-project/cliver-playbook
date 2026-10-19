"""RAG-owned runtime settings through the generic admin API (ADR-0021).

The RAG package registers the section; the identity package serves it. These
tests pin the ownership boundary: choices come from the live stage
registries, validation runs before the live Settings instance is touched,
secrets are write-only (stored, never returned) unless the environment
manages them, and a reset restores the startup baseline.
"""

from __future__ import annotations

import pytest

from cliver_playbook.app.basic import runtime


@pytest.fixture(autouse=True)
def _skip_audit_write(monkeypatch):
    """The identity audit table is PostgreSQL-shaped and is not part of this
    SQLite fixture. Audit persistence is asserted in the user package's suite;
    here the settings behavior is what matters."""

    async def _noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("cliver_playbook.app.user.api.admin_settings.write_audit", _noop)


def _sections(body: list[dict]) -> dict[str, dict]:
    return {section["key"]: section for section in body}


def _field(section: dict, name: str) -> dict:
    return next(field for field in section["fields"] if field["name"] == name)


async def _rag_section(client) -> dict:
    resp = await client.get("/api/v1/admin/settings", headers={})
    assert resp.status_code == 200, resp.text
    return _sections(resp.json())["rag"]


async def test_sections_include_the_rag_package(client):
    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 200
    keys = _sections(resp.json())
    assert {"user", "rag"} <= set(keys)
    assert keys["rag"]["title"] == "RAG pipeline"


async def test_stage_choices_come_from_live_registries(client):
    section = await _rag_section(client)
    assert set(_field(section, "chunker")["enum"]) >= {"recursive", "docx", "html"}
    assert set(_field(section, "embedder")["enum"]) >= {"stub", "cliver-core"}
    assert set(_field(section, "retriever")["enum"]) == {"pgvector-hybrid", "bm25-only"}
    assert set(_field(section, "reranker")["enum"]) >= {"noop", "cliver-core"}
    assert set(_field(section, "llm")["enum"]) >= {"stub", "cliver-core"}
    # Only chat has a protocol choice: embeddings and rerank are one-shot
    # requests with a single wire shape in cliver-core.
    assert set(_field(section, "cliver_llm.protocol")["enum"]) == {"openai", "anthropic"}
    field_names = {field["name"] for field in section["fields"]}
    assert "cliver_embed.protocol" not in field_names
    assert "cliver_rerank.protocol" not in field_names


async def test_cliver_bindings_share_one_group_with_a_subgroup_per_purpose(client):
    section = await _rag_section(client)
    cliver_fields = [field for field in section["fields"] if field["name"].startswith("cliver_")]
    assert cliver_fields
    assert {field["group"] for field in cliver_fields} == {"cliver-core"}
    assert {field["group_title"] for field in cliver_fields} == {"cliver-core model access"}
    # Each purpose folds independently inside the group, and has its own
    # model and credential.
    titles = {"llm": "LLM", "embed": "Embedding", "rerank": "Rerank"}
    for purpose, title in titles.items():
        purpose_fields = [
            field for field in cliver_fields if field["name"].startswith(f"cliver_{purpose}.")
        ]
        assert purpose_fields
        assert {field["subgroup"] for field in purpose_fields} == {purpose}
        assert {field["subgroup_title"] for field in purpose_fields} == {title}
        assert _field(section, f"cliver_{purpose}.model")["subgroup"] == purpose
        assert _field(section, f"cliver_{purpose}.api_key")["secret"] is True


async def test_update_applies_live_and_reports_runtime_source(client):
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={
            "values": {
                "chunk_size": 1024,
                "chunk_overlap": 128,
                "top_k": 30,
                "rerank_top_k": 6,
            }
        },
    )
    assert resp.status_code == 200, resp.text
    section = resp.json()
    assert _field(section, "chunk_size")["value"] == 1024
    assert _field(section, "chunk_size")["source"] == "runtime"
    assert _field(section, "top_k")["value"] == 30

    live = runtime.configured_settings().rag
    assert (live.chunk_size, live.chunk_overlap, live.top_k, live.rerank_top_k) == (
        1024,
        128,
        30,
        6,
    )


async def test_chunk_overlap_must_stay_below_chunk_size(client):
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"chunk_overlap": 512}},
    )
    assert resp.status_code == 400
    assert "chunk_overlap" in resp.json()["detail"]

    equal = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"chunk_size": 100, "chunk_overlap": 100}},
    )
    assert equal.status_code == 400

    # Nothing was applied or stored by the rejected updates.
    live = runtime.configured_settings().rag
    assert (live.chunk_size, live.chunk_overlap) == (512, 64)


async def test_unknown_stage_and_bad_protocol_are_rejected(client):
    bad_stage = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"embedder": "does-not-exist"}},
    )
    assert bad_stage.status_code == 400
    assert "embedder" in bad_stage.json()["detail"]

    bad_protocol = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"cliver_llm.protocol": "grpc"}},
    )
    assert bad_protocol.status_code == 400


async def test_secret_is_write_only_and_stored(client):
    from cliver_playbook.app.basic.runtime_settings import load_overrides

    # Writable, but the stored value is never returned.
    section = await _rag_section(client)
    secret = _field(section, "cliver_llm.api_key")
    assert secret["secret"] is True
    assert secret["read_only"] is False
    assert secret["value"] is None
    assert secret["env_var"] == "CLIVER_RAG__CLIVER_LLM__API_KEY"
    assert secret["configured"] is False

    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"cliver_llm.api_key": "sk-stored"}},
    )
    assert resp.status_code == 200, resp.text
    updated = _field(resp.json(), "cliver_llm.api_key")
    assert updated["value"] is None
    assert updated["configured"] is True
    assert updated["source"] == "runtime"
    assert runtime.configured_settings().rag.cliver_llm.api_key == "sk-stored"

    # Persisted with the section, so the startup overlay can apply it.
    overrides = await load_overrides()
    assert overrides["rag"]["cliver_llm.api_key"] == "sk-stored"

    # The API key is masked in the audit payload.
    from cliver_playbook.app.basic.runtime_settings import get_settings_section, redact_values

    section_def = get_settings_section("rag")
    assert section_def is not None
    assert redact_values(section_def, {"cliver_llm.api_key": "sk-stored"}) == {
        "cliver_llm.api_key": "<redacted>"
    }


async def test_environment_key_wins_and_locks_the_secret(client, monkeypatch):
    monkeypatch.setenv("CLIVER_RAG__CLIVER_LLM__API_KEY", "present")
    field = _field(await _rag_section(client), "cliver_llm.api_key")
    assert field["read_only"] is True
    assert field["source"] == "environment"
    assert field["configured"] is True
    assert field["value"] is None

    rejected = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"cliver_llm.api_key": "plaintext-leak"}},
    )
    assert rejected.status_code == 400
    assert "CLIVER_RAG__CLIVER_LLM__API_KEY" in rejected.json()["detail"]


async def test_environment_managed_stage_is_read_only(client, monkeypatch):
    monkeypatch.setenv("CLIVER_RAG__EMBEDDER", "stub")
    field = _field(await _rag_section(client), "embedder")
    assert field["read_only"] is True
    assert field["source"] == "environment"

    rejected = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"embedder": "stub"}},
    )
    assert rejected.status_code == 400
    assert "CLIVER_RAG__EMBEDDER" in rejected.json()["detail"]


async def test_cliver_llm_binding_is_editable_without_the_secret(client):
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={
            "values": {
                "cliver_llm.model": "example-model",
                "cliver_llm.base_url": "http://127.0.0.1:9999/v1",
                "cliver_llm.protocol": "anthropic",
                "cliver_llm.provider_name": "example",
                "cliver_llm.params": {"temperature": 0.1},
            }
        },
    )
    assert resp.status_code == 200, resp.text
    section = resp.json()
    assert _field(section, "cliver_llm.model")["value"] == "example-model"
    assert _field(section, "cliver_llm.protocol")["value"] == "anthropic"

    binding = runtime.configured_settings().rag.cliver_llm
    assert binding.model == "example-model"
    assert binding.base_url == "http://127.0.0.1:9999/v1"
    assert binding.protocol == "anthropic"
    assert binding.provider_name == "example"
    assert binding.params == {"temperature": 0.1}


async def test_embed_and_rerank_bindings_are_editable(client):
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={
            "values": {
                "cliver_embed.model": "embed-model",
                "cliver_embed.api_key": "sk-embed",
                "cliver_embed.base_url": "http://127.0.0.1:9999/v1",
                "cliver_embed.path": "/custom/embeddings",
                "cliver_embed.provider_name": "example",
                "cliver_embed.dim": 768,
                "cliver_embed.params": {"dimensions": 768},
                "cliver_rerank.model": "rerank-model",
                "cliver_rerank.api_key": "sk-rerank",
                "cliver_rerank.base_url": "http://127.0.0.1:9999/v1",
                "cliver_rerank.path": "/custom/rerank",
                "cliver_rerank.params": {"top_n": 5},
            }
        },
    )
    assert resp.status_code == 200, resp.text
    section = resp.json()
    assert _field(section, "cliver_embed.dim")["value"] == 768
    assert _field(section, "cliver_embed.api_key")["value"] is None
    assert _field(section, "cliver_embed.api_key")["configured"] is True
    assert _field(section, "cliver_rerank.api_key")["value"] is None
    assert _field(section, "cliver_rerank.api_key")["configured"] is True

    rag = runtime.configured_settings().rag
    assert rag.cliver_embed.model == "embed-model"
    assert rag.cliver_embed.api_key == "sk-embed"
    assert rag.cliver_embed.path == "/custom/embeddings"
    assert rag.cliver_embed.dim == 768
    assert rag.cliver_embed.params == {"dimensions": 768}
    assert rag.cliver_rerank.model == "rerank-model"
    assert rag.cliver_rerank.api_key == "sk-rerank"
    assert rag.cliver_rerank.path == "/custom/rerank"
    assert rag.cliver_rerank.params == {"top_n": 5}

    from cliver_playbook.app.rag.embedding.cliver import CliverCoreEmbedder
    from cliver_playbook.app.rag.reranking.cliver import CliverCoreReranker

    # The registry caches stage instances; they must read the live binding.
    assert CliverCoreEmbedder().id == "cliver-core@embed-model@768"
    assert CliverCoreReranker().model_id == "cliver-core@rerank-model"


async def test_bad_embedding_dim_is_rejected(client):
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"cliver_embed.dim": 0}},
    )
    assert resp.status_code == 400
    assert runtime.configured_settings().rag.cliver_embed.dim != 0


async def test_params_cannot_shadow_binding_arguments(client):
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"cliver_embed.params": {"base_url": "http://elsewhere/v1"}}},
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


async def test_persisted_binding_and_secret_are_restored_at_startup(client):
    """The cliver-core configuration is settings state, not process memory.

    A restart resolves the static layers and then the lifespan overlays the
    stored row; the credential must come back even though it is never
    returned by the API.
    """
    from cliver_playbook.app.basic.runtime_settings import load_persisted_settings

    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={
            "values": {
                "cliver_embed.model": "embed-model",
                "cliver_embed.base_url": "http://127.0.0.1:9999/v1",
                "cliver_embed.api_key": "sk-restored",
            }
        },
    )
    assert resp.status_code == 200, resp.text

    # Simulate the static configuration a fresh process starts with.
    live = runtime.configured_settings().rag.cliver_embed
    live.model = ""
    live.base_url = ""
    live.api_key = ""

    await load_persisted_settings()

    live = runtime.configured_settings().rag.cliver_embed
    assert live.model == "embed-model"
    assert live.base_url == "http://127.0.0.1:9999/v1"
    assert live.api_key == "sk-restored"


async def test_cached_llm_stage_sees_the_updated_binding(client):
    from cliver_playbook.app.rag.llm import get_llm

    # The registry caches one instance per stage for the process lifetime.
    llm = get_llm("cliver-core")
    resp = await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"cliver_llm.model": "runtime-model"}},
    )
    assert resp.status_code == 200, resp.text
    assert llm.model_id == "cliver-core@runtime-model"


async def test_reset_restores_the_startup_values(client):
    await client.put(
        "/api/v1/admin/settings/rag",
        json={"values": {"chunk_size": 2048, "chunk_overlap": 256}},
    )
    assert runtime.configured_settings().rag.chunk_size == 2048

    resp = await client.delete("/api/v1/admin/settings/rag")
    assert resp.status_code == 200, resp.text
    section = resp.json()
    assert _field(section, "chunk_size")["value"] == 512
    assert _field(section, "chunk_size")["source"] == "config"
    assert runtime.configured_settings().rag.chunk_size == 512
    assert runtime.configured_settings().rag.embedder == "stub"
