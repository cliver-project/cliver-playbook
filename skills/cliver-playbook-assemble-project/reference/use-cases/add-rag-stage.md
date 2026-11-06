# Add a RAG stage

## Use when

A project needs a chunker, embedder, retriever, reranker, or LLM that the
playbook does not ship, or a project-specific implementation of one. Prefer an
existing stage with different settings first; only implement a new stage when
the behavior, not the configuration, is different.

Profile: `rag` or `mcp`.

## Do

### 1. Pick the stage registry

Each stage owns a registry with the same `register(name, factory)` contract:

| Stage | Import | Settings field |
|---|---|---|
| chunker | `cliver_playbook.app.rag.chunking.registry` | `rag.chunker` |
| embedder | `cliver_playbook.app.rag.embedding.registry` | `rag.embedder` |
| retriever | `cliver_playbook.app.rag.retrieval.registry` | `rag.retriever` |
| reranker | `cliver_playbook.app.rag.reranking.registry` | `rag.reranker` |
| LLM | `cliver_playbook.app.rag.llm.registry` | `rag.llm` |

```python
# app/rag_stages.py
from cliver_playbook.app.rag.chunking import registry as chunkers

chunkers.register("orders-markdown", lambda: OrdersMarkdownChunker())
```

The registry owns the instance lifetime; model-backed stages memoize the first
factory result and share it process-wide. Return a fully configured instance
and do not mutate it after registration. Names are process-wide and a
duplicate registration raises, so use a project-specific name.

### 2. Implement the stage protocol

A chunker must provide `name`, `version`, `options_model`, and `split(...)` as
defined by the package's `chunking/base.py` protocol. The other stages have
equivalent protocols under their own `base.py`; copy the smallest built-in
implementation as the shape, not as a fork.

All model access goes through cliver-core. A stage must not call an OpenAI,
Anthropic, or other provider endpoint directly; use the stage's cliver-core
binding (see `rag.cliver_llm`, `rag.cliver_embed`, `rag.cliver_rerank`). If a
new transport is genuinely needed, add it to cliver-core, not here.

### 3. Register before the app serves the catalog

```python
# app/__init__.py
from app import permissions, rag_stages  # noqa: F401 — before the first request
```

Registration must happen before `GET /api/v1/rag/stages` is first served and
before any upload/search resolves a stage by name. The admin settings dropdown
reads the registry names through the same process.

### 4. Select the stage in settings

```yaml
rag:
  chunker: orders-markdown
```

Or override it at runtime through the RAG settings section when the field is
editable. A name that is not registered fails when resolved; it does not fall
back silently.

## Verify

```sh
uv run uvicorn --factory app.app:create_app --port 8000
curl -fsS http://127.0.0.1:8000/api/v1/rag/stages
```

The stage name appears under its category. Upload a document that exercises
the new implementation and confirm the chunk/embedding/retrieval result.
Cover the failure path: an unknown name produces a clear configuration error,
not a generic 500. Run the RAG package's tests plus the project's integration
test.

## Pitfalls

- **Do not import the registry module just to register a name after the first
  request.** Registration is process-wide and first-import wins.
- **A model-backing stage without a cliver-core binding is unusable**, even if
  it is listed. Configure the binding and keep the API key in the environment
  or a write-only settings field.
- **Do not copy a playbook stage to change a setting.** Settings and registries
  are the seam; vendoring a stage costs every future fix.
- **A stage that is reusable beyond this product belongs upstream.** Follow the
  upstream loop instead of keeping a private fork.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/registry.py`
  — the registry shape shared by every stage.
- `var/playbook/packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/base.py`
  — the chunker protocol.
- `var/playbook/packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/stages.py`
  — the catalog endpoint and registry discovery.
- Deep dive: `reference/decision-guide.md` section "Custom RAG stage".
