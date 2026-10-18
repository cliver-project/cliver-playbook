# ADR-0018: RAG as a composable package with pluggable stages

**Status:** Accepted (2026-10-18).
**Context:** The playbook needs a knowledge-base capability: a user uploads a
document, chooses how it is chunked, embedded, retrieved, reranked and answered
from, and then holds a grounded conversation over it. The stacks in place
already supply what should be reused — the composition contract (ADR-0015),
the settings inheritance and process runtime (ADR-0016), the identity package's
RBAC and `require_perm` gates, its `auth_tokens` session and its `audit_logs`
table, and the MCP package's aggregate migration entry point (ADR-0017). The
risk was building a second, parallel stack (its own auth checks, its own audit
table, its own settings object, hardcoded model choices) that would drift from
the identity domain it is supposed to sit on.

## Decision

1. **A new backend package, fourth in the dependency chain:**
   `cliver-playbook-app-rag` (`cliver_playbook.app.rag`), depending on `user`.
   The settings chain becomes `basic <- user <- rag <- mcp`; the mcp package's
   `Settings` extends the rag one, its `create_app` includes the rag `ROUTERS`
   in the same `include_router` loop, and `migrate.run_all_migrations` applies
   the rag chain after basic and user. A composed install therefore serves the
   knowledge base through the same application, the same permission system and
   the same audit table with no additional assembly.
2. **Every RAG stage is a protocol plus a name registry.** `chunking`,
   `embedding`, `retrieval`, `reranking` and `llm` each define a small Protocol
   (split, embed, retrieve, rerank, generate), a registry keyed by name, and at
   least one production implementation plus one offline implementation
   (`recursive`/`markdown`/`code`/`pdf`; `bge-m3`/`stub`; `pgvector-hybrid`/
   `bm25-only`; `bge-reranker-v2-m3`/`noop`; `stub`). Stage names and their
   knobs are settings (`settings.rag`), and the upload, index, search and chat
   requests may override them per call. Adding a new implementation means
   writing the class and registering it — no route or schema edit.
3. **Ingestion is two requests on purpose.** `POST /documents/upload` runs the
   chunker and persists chunks with `status="pending"`, returning a preview so
   the UI can show what the chosen chunker produced. `POST /{id}/index` then
   runs the embedder and flips the document to `indexed`. This keeps
   model-loading, potentially slow embedding out of the upload request and lets
   the user change the embedder after inspecting the chunks. Chunk ids are
   content hashes; a document id hashes `source_uri` plus the file content, so
   re-uploading the same file updates the same row and re-indexing replaces
   embeddings instead of duplicating them.
4. **One embedding table with an unconstrained vector column and a per-row
   dimension.** The embedder is a per-document choice, so the column cannot pin
   one dimension. pgvector indexes need one dimension class: the HNSW index is
   a partial expression index on the production default
   (`((embedding::vector(1024)) vector_cosine_ops) WHERE dim = 1024`), and the
   dense query spells the same expression and adds the same predicate when the
   query embedding is 1024-d, making the index eligible; other dimensions fall
   back to a sequential scan. Documents embedded at another dimension remain
   reachable through the lexical leg instead of becoming invisible.
5. **Hybrid retrieval fuses dense and lexical legs with reciprocal rank
   fusion (k = 60).** RRF is scale-free, so it needs no score calibration
   between cosine distances and `ts_rank_cd`. Fused scores are rank sums
   (~0.016 per contributing leg), *not* similarities: relevance floors must
   never be applied to them. The chat floor applies only to rerankers that
   declare `produces_relevance_scores` (a real cross-encoder); with a noop
   reranker no floor is applied. If nothing survives, the generator is skipped
   and the endpoint returns an explicit "no relevant context" refusal — a
   grounded assistant must fail closed, not hallucinate.
6. **Auth and audit are the identity domain's, not a copy.** Routers use the
   existing `Viewer`/`require_perm` gate. The rag package registers its four
   `rag:*` codes into the live permission catalog at import (the identity
   migration seeds admin from that live catalog, ADR-0017), so a composed
   install grants them on a fresh database and a user-only install is
   untouched. Audit rows go to the shared `audit_logs` table through a
   best-effort wrapper; user-supplied text is never stored — search queries and
   chat questions are recorded as a short SHA-256 fingerprint, and chat records
   hit counts and stage names.
7. **The frontend discovers stages from the server.** `GET
   /api/v1/rag/stages` renders every registry (name, model id, version,
   dimension) plus the configured defaults. The Web UI builds its selectors
   from that response rather than from a hardcoded list, so a new embedder or
   reranker becomes selectable when it is registered, not when someone updates
   the UI.
8. **Offline implementations make the defaults testable.** The embedder stub
   is deterministic and emits 64-d vectors; the noop reranker and stub LLM
   require no model download. Unit suites run on SQLite against the lexical
   retriever, while the composed package's tests run on real PostgreSQL against
   the migrated pgvector schema — the only place the dense SQL, the tsvector
   leg and the audit write are exercised end to end.

## Why

- Reusing the identity stack keeps one permission model, one token lifecycle
  and one audit stream: revoking a user's token or changing a role affects RAG
  endpoints through the same path as every other API, with no extra logic.
- Protocols plus registries keep the module extensible without touching the
  HTTP surface; the stage catalog makes the extensibility visible to the UI.
- The split upload/index flow mirrors the actual user decision (inspect the
  chunks, then commit to an embedder) and keeps slow model work off the upload
  path.
- The unconstrained vector column avoids a schema migration per embedder while
  still indexing the production dimension, which is the documented pgvector
  pattern for mixed-dimension columns.

## Alternatives considered

- **A separate RAG service/package with its own auth and audit.** Rejected: it
  duplicates RBAC, token verification and audit at the first divergence, and
  the composition contract already supports in-process packages.
- **A fixed-dimension vector column.** Rejected: the stub and hosted embedders
  differ in dimension, and altering the column per model choice is a migration
  per experiment. The partial expression index keeps the common path indexed.
- **Pinning the retriever's stage choice in code or hardcoding the UI lists.**
  Rejected: stage selection is the product feature; discovery from the server
  keeps the UI and registries in lockstep.
- **Applying a relevance floor to fused RRF scores.** Rejected: RRF sums are
  rank-derived and not comparable to cosine or reranker relevance; a 0.2 floor
  would refuse every hit. The floor belongs to rerankers that emit normalized
  relevance scores.
- **An in-memory BM25 index.** Rejected: the chunk table is the source of
  truth, an in-memory index must be rebuilt on every write and would diverge
  across processes; the lexical implementation reads the table per query.

## Non-goals

- Multi-tenant collections and per-user document isolation (the knowledge base
  is shared; access is gated by `rag:*` permissions).
- Hosted vector databases, sparse/learned sparse embeddings, and streaming
  generation.
- Re-implementing retrieval math: the pgvector SQL uses the database's own
  distance operators and full-text search.

## Risks

- pgvector is an extension: the compose service now uses the pgvector image,
  and the rag migration runs `CREATE EXTENSION IF NOT EXISTS vector`. A stock
  PostgreSQL image fails that migration loudly — the correct outcome, since the
  package cannot function without the extension.
- The HNSW expression and the query expression must stay textually aligned or
  the planner silently falls back to a sequential scan; the retriever keeps the
  two constants next to each other and the composed test asserts dense results
  on PostgreSQL.
- Model-backed stages load large weights. Defaults stay offline-capable, the
  BGE implementations load lazily inside a lock, and inference runs in a
  worker thread so the event loop keeps serving requests.
- The audit wrapper is best-effort by design; a failure must never fail the
  user's request. The composed PostgreSQL test asserts the row actually lands,
  because SQLite unit tests have no audit table and would hide that class of
  bug.
