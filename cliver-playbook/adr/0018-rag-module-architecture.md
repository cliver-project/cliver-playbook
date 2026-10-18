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
9. **The query embedder is a per-call override on search and chat.** The
   embedder is chosen per document at upload time, so the query side must be
   able to name the same model: vectors from different embedders live in
   different spaces and usually differ in dimension, and the dense leg matches
   only rows of the query's dimension. Without the override, a document
   indexed with a non-default embedder could never be found by the dense leg,
   and a non-default choice in the UI would silently degrade to lexical-only
   retrieval. The override is validated against the embedder registry before
   retrieval starts, and is recorded in the audit row.

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

## Amendments after independent review (2026-10-18)

The implementation was reviewed independently on the backend and the frontend.
The decisions below clarify or harden the original text without replacing any
of it; this section is appended, and the earlier sections stay as written.

1. **The permission set stays at four codes; there is no admin read code.**
   `/admin/rag` is gated by `rag:documents:read` and reads the same shared
   corpus as `/rag/documents`. v1 has no per-user ownership, so an
   `rag:admin:read` would gate nothing the server enforces differently. The
   operator page differs by detail and audience, not by authority.
2. **Mode support is a declared retriever capability, not a request hint.**
   Each retriever exposes `modes`; the stage catalog forwards it, search and
   chat reject an unsupported mode with 422 and a list of supported values, and
   the response reports both `requested_mode` and the `mode` that actually ran.
   A lexical-only retriever may accept `hybrid` and report `sparse`; the UI
   renders the effective mode and flags the fallback. This prevents lexical
   results from being labelled as a dense/hybrid run.
3. **The stage catalog also reports corpus facts.** `corpus.embedders` lists
   the embedders recorded on `indexed` documents. The chat page offers only
   those models as query embedders (the server default wins when present,
   otherwise the first corpus embedder), because a registered model that never
   indexed anything guarantees an empty dense leg. When the corpus is empty the
   choice is left to the server default and the UI says so.
4. **Indexing accepts an embedder override and keeps identity consistent.**
   The user may change the embedder after reviewing the preview; the index
   endpoint validates the override, replaces all embedding rows, and updates
   the document's `embedder_id` so `rag_documents.embedder_id` and
   `rag_chunk_embeddings.embedder_version` always describe the same model. A
   bad override is rejected without corrupting the document; re-indexing with
   the same embedder is idempotent unless `force=true`.
5. **Upload failures never destroy a live document.** A rejected re-upload
   (parse failure, chunker failure) only creates a `failed` row when the
   document did not previously exist. An existing indexed document keeps its
   chunks and status; the audit row records the rejected attempt. Concurrent
   uploads/indexes of the same content-hash id map an `IntegrityError` to a
   stable 409 instead of a driver-level 500.
6. **The ingestion surface is bounded.** Uploads read at most
   `rag.max_upload_bytes + 1` bytes and reject an oversized file with 413
   before parsing. Title, filename and MIME type are length-checked against
   their columns at the request boundary. Chunk size and overlap are validated
   before the splitter runs.
7. **Documents can be deleted.** `DELETE /rag/documents/{id}` removes the
   document, its chunks and its embeddings, and audits the stage choices. This
   is the other half of a manageable shared corpus; without it a bad upload
   would be permanent.
8. **Audit rows carry the caller and both outcomes.** RAG audit calls pass the
   `Viewer` and the `Request`, so rows record `user_id`, `username`, IP and
   user agent. Retrieval and pipeline failures are audited with `ok=False`;
   a grounded refusal is `ok=True` with `no_hits` in the detail, because
   finding nothing is a completed request. The audit wrapper remains
   best-effort: an audit write failure never fails the user's request.
9. **Model-backed registries memoize instances.** The BGE embedder and
   reranker keep their lazy-load lock and loaded weights on the instance;
   returning a fresh wrapper per lookup would reload weights per request. The
   stateless retriever and LLM share the contract so the seam is uniform.
   Chunkers stay pure functions and are intentionally outside it.
10. **The UI follows the server's truth.** Stage dropdowns show `model_id` and
    dimension; the query mode list is filtered by the selected retriever;
    results display the question that produced them, the effective mode, and
    localized failure reasons; uploading/indexing/deleting are hidden without
    `rag:documents:write` and search-only is hidden without
    `rag:search:read`; timestamps follow the UI language. Failures invalidate
    the document/catalog queries so a server-side `failed` row is visible even
    when the toast is missed.
