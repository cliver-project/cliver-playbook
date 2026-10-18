---
name: rag-module-design
description: RAG knowledge-base module design for cliver-playbook — the spec the implementation plan argues from
---

# RAG Knowledge-Base Module — Design

**Date:** 2026-10-18
**Status:** Approved (user away, "use the one you recommend" applied)

## Intent and the why

cliver-playbook is a personal engineering asset library — three composable
packages (basic, user, mcp) that a new project assembles instead of
re-deriving. The user wants a fourth capability: a **RAG knowledge-base
module** so that a project can ingest documents, store embeddings, and
answer user questions from the corpus — with the chunking strategy and the
embedder being **selectable in the Web UI per upload**, so the operator
sees the pipeline running end to end.

## Goals

- A working `cliver-playbook-app-rag` package (backend) and
  `cliver-playbook-app-rag` package (frontend) added to the existing
  workspace without breaking anything.
- **Per-stage user choice in the Web UI during upload**: the user picks
  a chunker and an embedder from dropdowns; advanced settings
  (chunk_size, chunk_overlap) are collapsible. Defaults are pre-selected
  so a one-click upload works.
- **Preview before commit**: after upload, the user sees the chunks
  (text + token count + chunk_id prefix) and the embedded-vector stats
  (count, dim, first/last). Only after the user clicks "Index" do the
  chunks land in the vector store.
- **End-user RAG chat**: a `/rag/chat` page where the user types a
  question, sees the retrieved chunks with citation badges, and gets an
  LLM-generated answer grounded in them. The RAG flow goes through
  retriever + reranker + LLM; the LLM call uses a model the user
  configures in the UI (default: a small local stub that returns
  "I do not have an LLM configured" so the chat is end-to-end without
  an LLM API key).
- **Pluggable**: every stage lives behind a protocol with at least two
  implementations (one offline-default, one optional hosted).
- **No new infra**: pgvector runs in the existing `docker-compose.yml`
  Postgres container. No new Docker images, no new system dependencies.
- **Reuse the playbook's existing seams**: Settings inheritance, ROUTERS
  contract, audit_logs (no ALTER), `auth_tokens` (no `rag_tokens`),
  permission codes registered into the identity catalog.

## Non-goals

- Not a vector DB replacement; pgvector is the only store.
- No Langfuse / Phoenix / LangSmith integration in v1 (in-app audit
  rows only — the audit_logs table is enough for v1).
- No code-split / dynamic-import of embedder SDKs at runtime; pip
  install everything once.
- No chat history / multi-turn in v1; one question = one answer.
- No streaming LLM responses in v1; full answer returned.
- No multi-tenant isolation in v1; the `cliver-playbook` SOP
  (one-user-one-app) holds.
- No code-aware tree-sitter for non-Python/TS/JS languages in v1
  (langchain `RecursiveCodeTextSplitter` is good enough; tree-sitter
  fine-tuning is a future task).

## Anti-goals

- **Never** an `mcp_tokens` analog; RAG uses the same `auth_tokens`
  table.
- **Never** an `ALTER TABLE` on `audit_logs`; agent/RAG details go in
  the JSONB `detail` field.
- **Never** a `Mount`; the RAG routers are ordinary `APIRouter`s
  composed by `include_router` (ADR-0017).
- **Never** an import-time side effect: a fresh `import
  cliver_playbook.app.rag` must not open a database connection, build
  an engine, read settings, or call any LLM.

## Constraints

- All code/comments/docs/commits in **English** (cliver-playbook
  standing rule).
- All identifiers and example strings **domain-neutral** (no client
  names, no project names, no real URLs, no real credentials).
- **Conventional commits**, each per-step commit green.
- **ADR append-only**: a new ADR is written for the RAG architecture
  choice (file: `adr/0018-rag-module-architecture.md`).
- Backend Python 3.12+, FastAPI >=0.143, async SQLAlchemy 2, asyncpg
  + psycopg (Alembic only), pydantic-settings >=2.16.
- Frontend React 19 + Vite 8 + Tailwind v4 + i18next + TanStack
  Query. **Source-only** package (ADR-0008), deep paths carry
  extensions.
- **No new Docker services**: pgvector is an extension of the existing
  Postgres 16 image (`postgres:16-alpine` + a one-line `initdb` or a
  dev-time `CREATE EXTENSION`). The `docker-compose.yml` is patched,
  not replaced.

## Architecture overview

The RAG module is one backend package and one frontend package. The
backend package owns **pluggable interfaces** for the five RAG stages
plus a default implementation per stage. The user picks per upload in
the Web UI; the chosen implementations are recorded in
`document_chunks.embedder_id` and `documents.chunker_id` so the
pipeline is auditable and re-runnable.

The five protocol shapes (named exactly as in the implementation plan):

```
Chunker.split(document) -> list[Chunk]
Embedder.embed(texts, mode, dim) -> list[list[float]]
Retriever.retrieve(query) -> list[Hit]
Reranker.rerank(query, hits) -> list[Hit]
LLMGenerator.generate(prompt) -> str  # also behind a protocol
```

Each protocol ships with at least two implementations: a default that
runs offline (CPU, no API key) and an optional hosted one. The default
chunkers are `RecursiveTextSplitter`, `MarkdownHeaderSplitter`, and
`CodeSplitter`. The default embedder is `BAAI/bge-m3` (CPU, 1024-d,
multilingual, dense+sparse+ColBERT from one pass). The default
reranker is `BAAI/bge-reranker-v2-m3` (CPU OK, ~2 GB RAM). The default
LLM is a "stub" that returns the top retrieved chunks verbatim as the
"answer" with a banner explaining the user hasn't configured a real
LLM.

The default retriever is pgvector HNSW + `tsvector` with RRF
(`k=60`); the `Retriever` protocol hides the store so a Qdrant or
BM25-only backend can drop in.

The retriever-rerank-LLM flow is the end-user chat. The retriever
alone is what powers the upload preview ("the most similar chunk
already in the index") — the upload preview is its own page, not a
chat. The chat is a separate page.

## How it lands in the playbook

- New backend package: `packages/backend/cliver-playbook-app-rag`
  (PEP 420 namespace, hatchling editable, src-layout, version_table
  `alembic_version_rag`, single chain revision `0001_rag_initial`).
- New frontend package: `packages/frontend/cliver-playbook-app-rag`
  (source-only, ADR-0008, deep paths carry extensions).
- Composed into the `app-mcp` dev shell: `mcp/dev/src/App.tsx`
  adds the RAG routes, `mcp/dev/src/main.tsx` adds
  `createI18n(userTranslations, mcpTranslations, ragTranslations)`.
- New permissions registered into the identity catalog:
  `rag:documents:read`, `rag:documents:write`, `rag:search:read`,
  `rag:chat:read`, `rag:admin:read`. The admin role automatically
  gets them (existing seed pattern).
- New root `docker-compose.yml` change: add
  `command: ["postgres", "-c", "shared_preload_libraries=vector"]`
  and a one-shot init container or `CREATE EXTENSION IF NOT EXISTS
  vector` at migration time. **The migration itself runs
  `CREATE EXTENSION IF NOT EXISTS vector` as its first statement.**
- New ADR: `adr/0018-rag-module-architecture.md` (append-only;
  references ADR-0015 / 0017 / 0003 / 0009).

## Why this design is "the recommended one"

- **pgvector** matches the existing Postgres stack — no new infra, no
  new ops surface, and it inherits the playbook's pattern of one
  database per process.
- **BGE-M3 + BGE-reranker-v2-m3** run on CPU; a fresh project with no
  API keys can do a full upload + RAG round-trip on a laptop. The
  pluggable surfaces let the same code path run Voyage 3 or OpenAI
  when an API key is set.
- **Content-hash chunk IDs** make re-indexing idempotent (the spec
  from the research note); the upload preview is just the chunker
  running and the embedder scoring against the current index.
- **In-app audit rows** are the only observability in v1; no
  OpenTelemetry, no Langfuse, no Phoenix. The detail JSONB carries
  chunker/embedder ids and the LLM's answer so an operator can
  reconstruct what happened.
- **Stub LLM by default** means the chat page is real and
  end-to-end without anyone wiring a paid API. The shape of the
  response is the same as a real LLM (citation badges, "I don't
  know" guard, latency breakdown) so swapping in a real generator
  is a one-line change.
- **Per-stage selection in the Web UI** is the user's explicit
  request — they want to see the pipeline. A single-screen upload
  with chunker + embedder dropdowns and a preview pane gives them
  that without overloading the chat page with config.

## What's left to the builder

- The exact Pydantic model field names for `Document`, `Chunk`, `Hit`
  (the protocol shapes in the plan are the names the implementer
  uses).
- The exact Pydantic model for `EmbeddingDocument` (the wire shape
  retriever.upsert takes) — defined in the plan's Task 4.
- The full list of i18n keys (en + zh) for the upload + chat pages —
  the plan ships ~30 keys, broken into `rag.documents.*`,
  `rag.chat.*`, `rag.common.*`.
- The exact `Settings` block for the `rag` package (the plan defines
  it in Task 1).
- The `CREATE EXTENSION IF NOT EXISTS vector` migration preamble
  (the plan defines it in Task 2).
- The file the plan modifies to add RAG permissions — `app/user/auth/permissions.py`
  gets a new `register_permission_codes()` call site? No — the RAG
  package's `__init__.py` does the registration, mirroring mcp's
  pattern. The plan spells this out in Task 3.

## What the user said

> "create such a module with both backend and frontend, try to use the
> existing modules if necessary. use the superpower skill to do the
> design, plan and execution. avoid asking me questions and try to
> implement that module by yourself by following the best practice so
> far, try to make each stage be selectable in the web ui when
> uploading a doc until it gets included to the database and be able
> to do RAG from users point of view. I will be away from keyboard."

## What the plan proves

That a new project starting from `cliver-playbook` can:
1. Open the Web UI, navigate to `/rag/documents`, upload a
   `.md`/`.txt`/`.pdf`/`.py`/`.js`/`.ts` file.
2. Pick `MarkdownHeaderSplitter` + `bge-m3` (or `Recursive` + `bge-m3`,
   or any other combination) from dropdowns. Adjust chunk size
   optionally.
3. Click "Preview" → see the chunk list with text, token count, and
   chunk_id. See "would be embedded with bge-m3 @ 1024-d" stat.
4. Click "Index" → chunks land in pgvector + tsvector. The document
   shows up in the "Indexed" tab with chunk count and indexed-at
   timestamp.
5. Navigate to `/rag/chat`, type "what does this corpus say about X?"
   → see the top-5 retrieved chunks with citation badges → see the
   stub-LLM answer composed from those chunks. The answer includes
   the chunk_ids it used.
6. The admin can `GET /api/v1/rag/admin/documents` and see every
   indexed document with its chunker + embedder ids.
7. The whole flow works on a fresh `make init && make db-init && make
   backend-start && make web-ui-start` with no API keys, no extra
   Docker, no extra services.

The audit row for every chunk indexed, every search, and every chat
answer is written to the existing `audit_logs` table (no ALTER).
