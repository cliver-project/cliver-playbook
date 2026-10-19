# ADR-0020: LLM generation through cliver-core

**Status:** Accepted (2026-10-19).
**Context:** ADR-0018 made the generator the fifth pluggable RAG stage but
shipped only the offline `stub`. Real generation would otherwise re-implement
provider selection, the OpenAI and Anthropic protocols, retries and request
option handling inside this repository. `cliver-core` is the user's agent core,
released as `cliver-core==0.3.0a1`; it already owns those concerns and adds
tool calling and the Re-Act loop. The requirement is that model calls go
through it so AI transports stay unified in one place.

## Decision

1. **A `cliver-core` generator stage implements the existing `LLM` protocol.**
   It builds a `ModelBinding.llm` from `rag.cliver_llm` and calls
   `AgentCore.chat` with the system prompt and the grounded prompt. No tools
   are supplied, so the loop ends after the first assistant message. The final
   text is returned to the chat endpoint unchanged.
2. **The synchronous seam stays.** The chat endpoint already runs generation
   in a worker thread (`asyncio.to_thread`); the adapter therefore executes
   the async cliver-core call with `asyncio.run` on that thread's private
   loop. Changing the `LLM` protocol to async would ripple through the
   endpoint and every existing implementation without changing observable
   behavior.
3. **Configuration is a nested `rag.cliver_llm` block** — `model`, `api_key`,
   `base_url`, `protocol` (`openai` or `anthropic`), optional `provider_name`,
   and `params` for default request options. It follows the same layered
   resolution as every other setting (`CLIVER_RAG__CLIVER_LLM__*`), and
   `api_key` stays out of the checked-in `app.yaml`.
4. **Nothing is validated at import or construction time.** The stage catalog
   instantiates every registered implementation to read metadata; an
   unconfigured deployment must still browse stages and use the stub. A
   missing model or endpoint raises an actionable `RuntimeError` when the
   stage is actually asked to generate.
5. **The dependency is plain `cliver-core==0.3.0a1`.** The `[mcp]` extra is
   not installed because RAG chat advertises no tools. It becomes required
   only if the generator itself needs MCP tools.
6. **`stub` remains the offline default.** Selecting `cliver-core` is a
   deployment choice (`CLIVER_RAG__LLM=cliver-core`), so a fresh clone still
   runs the whole pipeline without an account or model download.

## Why

- One transport and one provider abstraction for every model call; a new
  provider is a cliver-core concern, not a RAG change.
- The stage catalog keeps working with zero configuration, and the failure
  for a misconfigured stage is a clear configuration error rather than a
  vendor-level HTTP error.
- Provider protocol, tool calling and the agentic loop remain available
  without changing the RAG seam.

## Alternatives considered

- **Call the OpenAI or Anthropic SDK directly from the RAG package.**
  Rejected: duplicates cliver-core's provider layer and creates two
  transports to maintain.
- **Make `LLM.generate` async and keep one long-lived `AgentCore`.** Rejected
  for now: it changes the seam and every implementation for no observable
  gain. The adapter builds and closes one client per request; the remote
  model is stateless, and the cost is connection setup rather than model
  loading.
- **Depend on `cliver-core[mcp]` preemptively.** Rejected: RAG chat exposes
  no tools; an unused MCP SDK and its transport dependencies are dead weight.

## Non-goals

- MCP tools or an agentic loop inside RAG chat.
- Migrating the local BGE embedder and reranker to cliver-core capabilities;
  they remain local model implementations behind their own stages.
- Streaming answers to the browser.

## Risks

- The pin is an alpha release (`0.3.0a1`); upgrades are deliberate and tested
  against the local fake-provider smoke test.
- `protocol` must match the endpoint (OpenAI-compatible vs Anthropic); a
  mismatch surfaces as a provider error mapped to the chat endpoint's stable
  500.
- A process-wide provider cannot be reused across short-lived event loops, so
  each generation constructs and closes an `AgentCore`. Revisit if connection
  setup becomes measurable.

## Amendment (2026-10-19)

Embeddings and reranking now have cliver-core-backed stages as well
(`cliver-core` in the embedder and reranker registries), each configured
through its own purpose binding. See ADR-0022. The non-goal above still
holds: the local BGE stages are not migrated and remain available alongside
the remote stages.
