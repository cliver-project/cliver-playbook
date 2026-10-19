# ADR-0022: cliver-core purpose bindings across RAG stages

**Status:** Accepted (2026-10-19).
**Context:** ADR-0020 introduced the `cliver-core` generator and established
that model transports belong in cliver-core rather than in a RAG-local
provider layer. The same argument applies to embeddings and reranking:
cliver-core's `ModelBinding` already describes per-purpose endpoints,
protocols, credentials, path overrides and default request options, and its
`embed` / `rerank` entry points speak to the providers directly. Implementing
a second remote transport inside RAG would duplicate that knowledge and drift.
The requirement is therefore that every model access this repository makes
goes through cliver-core, configured per purpose, and that the configuration
is editable as part of the application's settings rather than only in
`app.yaml` or the environment.

## Decision

1. **cliver-core is the single model-access layer.** RAG stages that call a
   remote model use a cliver-core `ModelBinding` and the matching cliver-core
   entry point. Adding a provider, protocol, or model family is a cliver-core
   change; RAG only selects a stage and supplies its purpose binding. A future
   model-backed capability that cliver-core does not expose is added to
   cliver-core first, not implemented locally.
2. **One binding per purpose, not one shared binding.** `rag.cliver_llm`,
   `rag.cliver_embed`, and `rag.cliver_rerank` are independent configuration
   blocks. A deployment commonly uses different providers, models, endpoints
   and credentials for chat, embeddings and reranking; a single binding would
   force them together. Each block carries `model`, `api_key`, `base_url`,
   optional `provider_name`, optional `path`, and `params`; `cliver_embed`
   also declares `dim`. `protocol` belongs to `cliver_llm` alone: chat has
   two first-class wire shapes (OpenAI and Anthropic), while embeddings and
   rerank are one-shot OpenAI-shaped POSTs with no Anthropic-protocol
   counterpart in cliver-core, so exposing a protocol there would be a knob
   with one valid value.
3. **Two new stages implement the existing RAG protocols.**
   `CliverCoreEmbedder` implements `Embedder` (`id`, `dim`,
   `max_input_tokens`, `supports_query_document_modes`, sync `embed`) and
   `CliverCoreReranker` implements `Reranker` (`name`, `model_id`,
   `produces_relevance_scores`, sync `rerank`). They register as
   `cliver-core`, so the stage catalog and per-request selection need no
   change.
4. **Adapters read settings live.** The registries cache one stage instance
   per name for the process lifetime, and the settings section mutates the
   bound Settings object in place. The adapters therefore hold no snapshot:
   `config`, `id`, `dim`, and `model_id` are properties over the current
   `rag.cliver_*` block. A cached instance created before the runtime was
   configured still sees an accepted runtime edit on the next call.
5. **The synchronous seam stays.** Both stage protocols are synchronous
   because their callers already run them in worker threads. The adapters
   execute the async cliver-core call with `asyncio.run` on that thread's
   private loop and build and close one binding per call; a provider's HTTP
   client is loop-affine and must not cross short-lived loops.
6. **Embedding identity includes the model and the vector size.**
   `CliverCoreEmbedder.id` is `cliver-core@<model>@<dim>` (or a
   digest-suffixed form that fits `rag_chunk_embeddings.embedder_version`,
   String(64)). Retrieval filters stored vectors by this id, which prevents a
   query from a changed model or size being compared against an
   incompatible vector space. `dim` is the declared output size; the adapter
   rejects a response with the wrong vector count or vector length with an
   actionable configuration error instead of storing corrupt vectors.
7. **Rerank results are remapped to the retriever's hits.** The adapter maps
   each provider item's index back onto the input `Hit`, copies it with the
   provider's relevance score, sorts best-first (independently of the
   provider's ordering promise), and applies `top_k`. Out-of-range indices are
   ignored. Empty input returns an empty list without contacting the provider.
   `produces_relevance_scores` is true because the provider score is the
   normalized scale `rag.score_floor` is defined on.
8. **Configuration is DB-backed through runtime settings.** The three blocks
   are fields of the RAG-owned settings section (ADR-0021) and are editable at
   Admin → Settings → RAG. Values are persisted in `app_settings`, applied
   live, and restored by reset. `api_key` fields are write-only: the API
   accepts and stores a replacement but never returns it, and audit rows mask
   it. An environment variable (`CLIVER_RAG__CLIVER_EMBED__API_KEY`, …) or
   `.env` entry still wins and makes the field read-only.
9. **The UI groups and folds the bindings.** The settings framework exposes
   optional `group`/`group_title` and nested `subgroup`/`subgroup_title`
   presentation metadata; fields sharing a key render under one heading. All
   cliver-core fields use the `cliver-core` group, with one subgroup per
   purpose (`llm`, `embed`, `rerank`). Groups and subgroups render as
   collapsible blocks, so the binding fields do not dominate the page. The
   owning frontend translates them through
   `settingsSections.rag.groups.cliver-core.title` and
   `.subgroups.<key>.title`, with the server's English title as fallback.
10. **Local stages remain first-class.** `bge-m3`,
    `bge-base-zh-v1.5`, and `bge-reranker-v2-m3` stay local implementations
    behind the same protocols. The `cliver-core` stages are additional
    choices, not a migration; the offline defaults (`stub`, `noop`, `stub`)
    still run a fresh clone with no account, endpoint, or model download.

## Why

- One transport, one credential model, one place to add a provider. RAG
  contributes stage semantics (chunk vectors, hit remapping, corpus identity)
  and nothing about wire protocols.
- Per-purpose bindings match how models are actually provisioned: chat,
  embedding and rerank endpoints differ in provider, model, size and
  credential. Sharing one configuration would be simultaneously too broad and
  too inflexible.
- Live properties keep a cached stage correct after an administrator edits
  the binding; requiring a restart would contradict ADR-0021's in-place update
  model.
- Including the model and dimension in the embedder id makes the most
  dangerous failure — comparing vectors from different spaces — impossible to
  reach through the normal retrieval path.

## Alternatives considered

- **Implement embeddings and rerank directly against the OpenAI/Cohere-compatible
  HTTP APIs in RAG.** Rejected: duplicates cliver-core's provider layer and
  creates two transports to maintain, exactly the outcome ADR-0020 avoided for
  chat.
- **One shared `cliver` binding for all purposes.** Rejected: chat, embeddings
  and rerank are commonly different providers and models; overloading one
  block would make the common case impossible to express.
- **Capture the config at stage construction.** Rejected: registry instances
  outlive a settings edit, so `dim`, `id` and the binding would silently
  describe the startup configuration rather than the one in force.
- **Reuse one long-lived binding/provider across calls.** Rejected: the
  provider builds an async HTTP client bound to the loop that created it, and
  each call runs on a short-lived worker loop. Construction cost is connection
  setup, not model loading.
- **Store model credentials only in the environment.** Rejected as the only
  path: the operator needs to configure and rotate each purpose from the UI.
  Write-only storage plus the environment override keeps both options
  available (ADR-0021 decision 7).

## Non-goals

- Migrating the local BGE stages to cliver-core. They remain local model
  implementations; cliver-core covers the remote path.
- Image, audio, video, TTS, ASR or other cliver-core purposes. RAG has no
  stage or storage seam for them today. When one is needed, the capability is
  added to cliver-core and only then surfaced as a RAG stage.
- Streaming, tool calling, or an agentic loop in the embedding and rerank
  stages.
- Re-embedding stored chunks automatically after a model change. Changing the
  embedder id makes old vectors invisible to new queries; re-indexing remains
  an explicit operator action.

## Risks

- **A model change silently strands old vectors.** Retrieval filters by
  embedder id, so old chunks stop matching instead of producing wrong
  results. The remedy is re-indexing, and the UI already reports which
  embedders have indexed rows.
- **Credentials at rest in `app_settings`.** The database is the trust
  boundary; the API never returns a secret and the audit log masks it.
  Deployments that do not accept plaintext pin the variable in the
  environment, which overrides the row and locks the field.
- **Misconfiguration surfaces at call time.** The stage catalog must list an
  unconfigured `cliver-core` stage without importing a provider, so a missing
  model or endpoint raises an actionable `RuntimeError` from the call rather
  than failing startup.
- **The cliver-core pin is an alpha (`0.3.0a1`).** Upgrades are deliberate and
  covered by the local fake-provider tests; a binding or result-shape change
  is a code change in these adapters.
- **Rerank scores are provider-defined.** They are treated as normalized
  relevance because that is the contract the stage advertises; a provider
  that returns raw logits would make `score_floor` behave differently.
