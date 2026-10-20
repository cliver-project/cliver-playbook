"""The RAG package's runtime settings section (ADR-0021).

RAG owns the settings that describe its pipeline: which registered stage
serves each role, the default chunk sizing, retrieval and reranking budgets,
the upload cap, and the cliver-core purpose bindings (chat, embeddings,
rerank). The bindings share one UI group, split into a collapsible
subsection per purpose, so model access is configured in a single place.
The admin settings API discovers this section through the registry in
``basic.runtime_settings`` and never re-implements its validation.

The stage-name choices come from the live registries, so installing a new
implementation makes it selectable without touching this module. Validation
runs before any assignment: a rejected update leaves the running pipeline
exactly as it was.

Secrets: the three ``api_key`` fields are declared with ``secret=True``. The
generic framework accepts a replacement, stores it with the section in
``app_settings``, and never returns it. Setting the matching environment
variable (``CLIVER_RAG__CLIVER_LLM__API_KEY``, …) overrides the stored value
and makes the field read-only, which keeps credentials out of the database
for deployments that prefer that.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from cliver_playbook.app.basic.runtime_settings import (
    SettingsField,
    SettingsSection,
    SettingsValidationError,
    register_settings_section,
)
from cliver_playbook.app.rag.settings import (
    CliverEmbedSettings,
    CliverLLMSettings,
    CliverRerankSettings,
)

SECTION_KEY = "rag"

# All cliver-core bindings render together under one heading so an operator
# sees the model-access configuration in one place instead of scattered
# among the pipeline knobs. Within that heading each purpose gets its own
# subgroup, so the three bindings fold independently.
CLIVER_GROUP = "cliver-core"
CLIVER_GROUP_TITLE = "cliver-core model access"

# Stage field -> the registry module that owns its names. Imported lazily so
# this module's import does not drag in every implementation; by registration
# time the registries are already part of the package's import graph.
_STAGE_MODULES = {
    "chunker": "cliver_playbook.app.rag.chunking.registry",
    "embedder": "cliver_playbook.app.rag.embedding.registry",
    "retriever": "cliver_playbook.app.rag.retrieval.registry",
    "reranker": "cliver_playbook.app.rag.reranking.registry",
    "llm": "cliver_playbook.app.rag.llm.registry",
}


def _stage_names() -> dict[str, list[str]]:
    import importlib

    return {
        field: sorted(importlib.import_module(module).names())
        for field, module in _STAGE_MODULES.items()
    }


class _RagRuntimeSettings(BaseModel):
    """Full validation model for the editable RAG configuration."""

    chunker: str
    embedder: str
    retriever: str
    reranker: str
    llm: str
    chunk_size: int = Field(ge=1)
    chunk_overlap: int = Field(ge=0)
    top_k: int = Field(ge=1)
    rerank_top_k: int = Field(ge=1)
    score_floor: float = Field(ge=0.0, le=1.0)
    pgvector_ef_search: int = Field(ge=1)
    max_upload_bytes: int = Field(ge=1)
    cliver_llm: CliverLLMSettings
    cliver_embed: CliverEmbedSettings
    cliver_rerank: CliverRerankSettings

    @model_validator(mode="after")
    def _check_stage_names(self) -> _RagRuntimeSettings:
        for field, names in _stage_names().items():
            value = getattr(self, field)
            if value not in names:
                raise ValueError(f"{field} must be one of: {', '.join(names)}")
        return self

    @model_validator(mode="after")
    def _check_chunk_sizes(self) -> _RagRuntimeSettings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

    @field_validator("cliver_llm")
    @classmethod
    def _check_protocol(cls, value: CliverLLMSettings) -> CliverLLMSettings:
        if value.protocol not in ("openai", "anthropic"):
            raise ValueError("cliver LLM protocol must be 'openai' or 'anthropic'")
        return value


def _fields() -> tuple[SettingsField, ...]:
    stages = _stage_names()
    return (
        SettingsField(
            name="chunker",
            label="Default chunker",
            type="enum",
            enum=tuple(stages["chunker"]),
            description="Used when an upload does not choose a chunker explicitly.",
            env_var="CLIVER_RAG__CHUNKER",
        ),
        SettingsField(
            name="embedder",
            label="Default embedder",
            type="enum",
            enum=tuple(stages["embedder"]),
            description="Vectors are tied to the embedder that produced them.",
            env_var="CLIVER_RAG__EMBEDDER",
        ),
        SettingsField(
            name="retriever",
            label="Default retriever",
            type="enum",
            enum=tuple(stages["retriever"]),
            description="Lexical-only or pgvector hybrid retrieval.",
            env_var="CLIVER_RAG__RETRIEVER",
        ),
        SettingsField(
            name="reranker",
            label="Default reranker",
            type="enum",
            enum=tuple(stages["reranker"]),
            description="Cross-encoder reranking for search and chat hits.",
            env_var="CLIVER_RAG__RERANKER",
        ),
        SettingsField(
            name="llm",
            label="Answer generator",
            type="enum",
            enum=tuple(stages["llm"]),
            description="The stub is offline; cliver-core calls a real model.",
            env_var="CLIVER_RAG__LLM",
        ),
        SettingsField(
            name="chunk_size",
            label="Default chunk size",
            type="integer",
            minimum=1,
            description="Characters per chunk unless an upload overrides it.",
            env_var="CLIVER_RAG__CHUNK_SIZE",
        ),
        SettingsField(
            name="chunk_overlap",
            label="Default chunk overlap",
            type="integer",
            minimum=0,
            description="Characters repeated between adjacent chunks; smaller than the chunk size.",
            env_var="CLIVER_RAG__CHUNK_OVERLAP",
        ),
        SettingsField(
            name="top_k",
            label="Retrieval depth",
            type="integer",
            minimum=1,
            description="Hits returned by the retriever before reranking.",
            env_var="CLIVER_RAG__TOP_K",
        ),
        SettingsField(
            name="rerank_top_k",
            label="Context size",
            type="integer",
            minimum=1,
            description="Hits kept after reranking and shown to the generator.",
            env_var="CLIVER_RAG__RERANK_TOP_K",
        ),
        SettingsField(
            name="score_floor",
            label="Relevance floor",
            type="number",
            minimum=0.0,
            maximum=1.0,
            description="Drop reranked hits below this normalized score; 0 disables the floor.",
            env_var="CLIVER_RAG__SCORE_FLOOR",
        ),
        SettingsField(
            name="pgvector_ef_search",
            label="pgvector search breadth",
            type="integer",
            minimum=1,
            description="HNSW candidates explored per query (raised to at least the limit).",
            env_var="CLIVER_RAG__PGVECTOR_EF_SEARCH",
        ),
        SettingsField(
            name="max_upload_bytes",
            label="Maximum upload size (bytes)",
            type="integer",
            minimum=1,
            description="Larger uploads are rejected before parsing.",
            env_var="CLIVER_RAG__MAX_UPLOAD_BYTES",
        ),
        # --- cliver-core model access (one grouped block) -----------------
        SettingsField(
            name="cliver_llm.model",
            label="cliver-core LLM model",
            type="string",
            description="Chat model identifier passed to cliver-core.",
            env_var="CLIVER_RAG__CLIVER_LLM__MODEL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="llm",
            subgroup_title="LLM",
        ),
        SettingsField(
            name="cliver_llm.api_key",
            label="cliver-core LLM API key",
            type="string",
            description="Write-only; stored with the settings and never returned. The environment variable overrides it.",
            env_var="CLIVER_RAG__CLIVER_LLM__API_KEY",
            secret=True,
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="llm",
            subgroup_title="LLM",
        ),
        SettingsField(
            name="cliver_llm.base_url",
            label="cliver-core LLM endpoint",
            type="string",
            description="OpenAI- or Anthropic-compatible endpoint; empty uses the provider default.",
            env_var="CLIVER_RAG__CLIVER_LLM__BASE_URL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="llm",
            subgroup_title="LLM",
        ),
        SettingsField(
            name="cliver_llm.protocol",
            label="cliver-core LLM protocol",
            type="enum",
            enum=("openai", "anthropic"),
            description="Must match the endpoint's wire protocol.",
            env_var="CLIVER_RAG__CLIVER_LLM__PROTOCOL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="llm",
            subgroup_title="LLM",
        ),
        SettingsField(
            name="cliver_llm.provider_name",
            label="cliver-core LLM provider name",
            type="string",
            description="Optional provider brand whose default endpoint supplies base_url.",
            env_var="CLIVER_RAG__CLIVER_LLM__PROVIDER_NAME",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="llm",
            subgroup_title="LLM",
        ),
        SettingsField(
            name="cliver_llm.params",
            label="cliver-core LLM request options",
            type="json",
            description="Default request options such as temperature or top_p.",
            env_var="CLIVER_RAG__CLIVER_LLM__PARAMS",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="llm",
            subgroup_title="LLM",
        ),
        SettingsField(
            name="cliver_embed.model",
            label="cliver-core embedding model",
            type="string",
            description="Embeddings model identifier passed to cliver-core.",
            env_var="CLIVER_RAG__CLIVER_EMBED__MODEL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_embed.api_key",
            label="cliver-core embedding API key",
            type="string",
            description="Write-only; stored with the settings and never returned. The environment variable overrides it.",
            env_var="CLIVER_RAG__CLIVER_EMBED__API_KEY",
            secret=True,
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_embed.base_url",
            label="cliver-core embedding endpoint",
            type="string",
            description="OpenAI-compatible embeddings endpoint; empty uses the provider default.",
            env_var="CLIVER_RAG__CLIVER_EMBED__BASE_URL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_embed.path",
            label="cliver-core embedding endpoint path",
            type="string",
            description="Path override; empty uses the standard endpoint (/embeddings).",
            env_var="CLIVER_RAG__CLIVER_EMBED__PATH",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_embed.provider_name",
            label="cliver-core embedding provider name",
            type="string",
            description="Optional provider brand whose default endpoint supplies base_url.",
            env_var="CLIVER_RAG__CLIVER_EMBED__PROVIDER_NAME",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_embed.dim",
            label="Embedding vector size",
            type="integer",
            minimum=1,
            description=(
                "Vector size the model returns; embeddings of another size are "
                "rejected. Change it together with the model."
            ),
            env_var="CLIVER_RAG__CLIVER_EMBED__DIM",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_embed.params",
            label="cliver-core embedding request options",
            type="json",
            description="Default request options such as dimensions, when the API supports it.",
            env_var="CLIVER_RAG__CLIVER_EMBED__PARAMS",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="embed",
            subgroup_title="Embedding",
        ),
        SettingsField(
            name="cliver_rerank.model",
            label="cliver-core rerank model",
            type="string",
            description="Rerank model identifier passed to cliver-core.",
            env_var="CLIVER_RAG__CLIVER_RERANK__MODEL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="rerank",
            subgroup_title="Rerank",
        ),
        SettingsField(
            name="cliver_rerank.api_key",
            label="cliver-core rerank API key",
            type="string",
            description="Write-only; stored with the settings and never returned. The environment variable overrides it.",
            env_var="CLIVER_RAG__CLIVER_RERANK__API_KEY",
            secret=True,
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="rerank",
            subgroup_title="Rerank",
        ),
        SettingsField(
            name="cliver_rerank.base_url",
            label="cliver-core rerank endpoint",
            type="string",
            description="Cohere/Jina/GLM-compatible rerank endpoint; empty uses the provider default.",
            env_var="CLIVER_RAG__CLIVER_RERANK__BASE_URL",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="rerank",
            subgroup_title="Rerank",
        ),
        SettingsField(
            name="cliver_rerank.path",
            label="cliver-core rerank endpoint path",
            type="string",
            description="Path override; empty uses the standard endpoint (/rerank).",
            env_var="CLIVER_RAG__CLIVER_RERANK__PATH",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="rerank",
            subgroup_title="Rerank",
        ),
        SettingsField(
            name="cliver_rerank.provider_name",
            label="cliver-core rerank provider name",
            type="string",
            description="Optional provider brand whose default endpoint supplies base_url.",
            env_var="CLIVER_RAG__CLIVER_RERANK__PROVIDER_NAME",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="rerank",
            subgroup_title="Rerank",
        ),
        SettingsField(
            name="cliver_rerank.params",
            label="cliver-core rerank request options",
            type="json",
            description="Default request options forwarded to the rerank endpoint.",
            env_var="CLIVER_RAG__CLIVER_RERANK__PARAMS",
            group=CLIVER_GROUP,
            group_title=CLIVER_GROUP_TITLE,
            subgroup="rerank",
            subgroup_title="Rerank",
        ),
    )


def _read(settings: Any) -> dict[str, Any]:
    rag = settings.rag
    return {
        "chunker": rag.chunker,
        "embedder": rag.embedder,
        "retriever": rag.retriever,
        "reranker": rag.reranker,
        "llm": rag.llm,
        "chunk_size": rag.chunk_size,
        "chunk_overlap": rag.chunk_overlap,
        "top_k": rag.top_k,
        "rerank_top_k": rag.rerank_top_k,
        "score_floor": rag.score_floor,
        "pgvector_ef_search": rag.pgvector_ef_search,
        "max_upload_bytes": rag.max_upload_bytes,
        "cliver_llm.model": rag.cliver_llm.model,
        "cliver_llm.api_key": rag.cliver_llm.api_key,
        "cliver_llm.base_url": rag.cliver_llm.base_url,
        "cliver_llm.protocol": rag.cliver_llm.protocol,
        "cliver_llm.provider_name": rag.cliver_llm.provider_name or "",
        "cliver_llm.params": dict(rag.cliver_llm.params),
        "cliver_embed.model": rag.cliver_embed.model,
        "cliver_embed.api_key": rag.cliver_embed.api_key,
        "cliver_embed.base_url": rag.cliver_embed.base_url,
        "cliver_embed.path": rag.cliver_embed.path or "",
        "cliver_embed.provider_name": rag.cliver_embed.provider_name or "",
        "cliver_embed.dim": rag.cliver_embed.dim,
        "cliver_embed.params": dict(rag.cliver_embed.params),
        "cliver_rerank.model": rag.cliver_rerank.model,
        "cliver_rerank.api_key": rag.cliver_rerank.api_key,
        "cliver_rerank.base_url": rag.cliver_rerank.base_url,
        "cliver_rerank.path": rag.cliver_rerank.path or "",
        "cliver_rerank.provider_name": rag.cliver_rerank.provider_name or "",
        "cliver_rerank.params": dict(rag.cliver_rerank.params),
    }


def _apply(settings: Any, values: dict[str, Any]) -> None:
    merged = {**_read(settings), **values}
    payload = {
        "chunker": merged["chunker"],
        "embedder": merged["embedder"],
        "retriever": merged["retriever"],
        "reranker": merged["reranker"],
        "llm": merged["llm"],
        "chunk_size": merged["chunk_size"],
        "chunk_overlap": merged["chunk_overlap"],
        "top_k": merged["top_k"],
        "rerank_top_k": merged["rerank_top_k"],
        "score_floor": merged["score_floor"],
        "pgvector_ef_search": merged["pgvector_ef_search"],
        "max_upload_bytes": merged["max_upload_bytes"],
        "cliver_llm": {
            "model": merged["cliver_llm.model"],
            "api_key": merged["cliver_llm.api_key"],
            "base_url": merged["cliver_llm.base_url"],
            "protocol": merged["cliver_llm.protocol"],
            "provider_name": merged["cliver_llm.provider_name"] or None,
            "params": merged["cliver_llm.params"] or {},
        },
        "cliver_embed": {
            "model": merged["cliver_embed.model"],
            "api_key": merged["cliver_embed.api_key"],
            "base_url": merged["cliver_embed.base_url"],
            "path": merged["cliver_embed.path"] or None,
            "provider_name": merged["cliver_embed.provider_name"] or None,
            "dim": merged["cliver_embed.dim"],
            "params": merged["cliver_embed.params"] or {},
        },
        "cliver_rerank": {
            "model": merged["cliver_rerank.model"],
            "api_key": merged["cliver_rerank.api_key"],
            "base_url": merged["cliver_rerank.base_url"],
            "path": merged["cliver_rerank.path"] or None,
            "provider_name": merged["cliver_rerank.provider_name"] or None,
            "params": merged["cliver_rerank.params"] or {},
        },
    }
    try:
        validated = _RagRuntimeSettings.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise SettingsValidationError(f"invalid RAG settings: {details}") from exc

    # Validate fully first, then mutate the live instance in place. Objects
    # that hold a reference to settings.rag keep seeing the change.
    for name in (
        "chunker",
        "embedder",
        "retriever",
        "reranker",
        "llm",
        "chunk_size",
        "chunk_overlap",
        "top_k",
        "rerank_top_k",
        "score_floor",
        "pgvector_ef_search",
        "max_upload_bytes",
    ):
        setattr(settings.rag, name, getattr(validated, name))
    for name in ("model", "api_key", "base_url", "protocol", "provider_name", "params"):
        setattr(settings.rag.cliver_llm, name, getattr(validated.cliver_llm, name))
    for name in ("model", "api_key", "base_url", "path", "provider_name", "dim", "params"):
        setattr(settings.rag.cliver_embed, name, getattr(validated.cliver_embed, name))
    for name in ("model", "api_key", "base_url", "path", "provider_name", "params"):
        setattr(settings.rag.cliver_rerank, name, getattr(validated.cliver_rerank, name))


RAG_SETTINGS_SECTION = SettingsSection(
    key=SECTION_KEY,
    title="RAG pipeline",
    description=(
        "Stage selection, chunking defaults, retrieval and reranking budgets, "
        "upload limits, and the cliver-core model bindings for chat, "
        "embeddings, and reranking."
    ),
    fields=_fields,
    read=_read,
    apply=_apply,
)

register_settings_section(RAG_SETTINGS_SECTION)
