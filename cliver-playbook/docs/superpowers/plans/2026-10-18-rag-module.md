# RAG Knowledge-Base Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a RAG knowledge-base module (backend + frontend) to cliver-playbook. Users upload documents in the Web UI, pick the chunking strategy and embedder per file, preview the chunks, then index them. End users then ask questions in a chat page and get a RAG answer (retrieved + reranked + LLM-generated) with citations.

**Architecture:** New `cliver-playbook-app-rag` package on each side, mirroring the existing app-basic/app-user/app-mcp split (PEP 420 namespace, hatchling editable, src-layout). All five RAG stages live behind protocol shapes (Chunker / Embedder / Retriever / Reranker / LLM) with multiple pluggable implementations; defaults ship. The user can override at the document level in the upload flow. Storage is pgvector (HNSW + halfvec + sparsevec) + Postgres `tsvector` with RRF fusion; the auth gate is the same `auth_tokens` table. The frontend is a source-only package (ADR-0008) added to the mcp dev shell (the full composition) as a new `extraNavItems` set.

**Tech Stack:** Python 3.12+, FastAPI 0.143+, SQLAlchemy 2 async + asyncpg, pgvector 0.8+ (HNSW + halfvec + sparsevec), psycopg (Alembic only), pydantic-settings, langchain-text-splitters 0.3+, sentence-transformers 3.x, FlagEmbedding (BGE-M3 + BGE-reranker-v2-m3), unstructured[pdf] (PDF parsing), rank-bm25 (BM25 fallback), openai SDK (hosted embedder option), Vite 8 + React 19 + Tailwind v4 + i18next + TanStack Query, pnpm 11.

**Spec:** `docs/superpowers/specs/2026-10-18-rag-module-design.md`

## Global Constraints

- **English-only** in code/comments/docs/commits (cliver-playbook standing rule).
- **Domain-neutral** identifiers and example strings. No client names, no project names, no real URLs, no real credentials. Repository files must never contain secrets — only `.env.example` placeholders.
- **Conventional commits** with `Co-Authored-By: Claude Code <noreply@anthropic.com>`. Each per-step commit green (ruff + the test for that step).
- **No client/project/URL/credential values** in any repo file (red line).
- **ADR append-only**: a new ADR is written (`adr/0018-rag-module-architecture.md`); existing ADRs not modified.
- **No `app.mount()`**: routers are ordinary `APIRouter`s composed by `include_router` (ADR-0017).
- **No `ALTER TABLE` on `audit_logs`**; RAG details go in JSONB `detail` (ADR-0014).
- **No new Docker services**; pgvector is an extension loaded into the existing `postgres:16-alpine` container.
- **Source-only frontend package** with deep paths carrying extensions (ADR-0008).
- PEP 420 namespace, hatchling editable (`dev-mode-dirs=["src"]`).
- Backend Python 3.12+, FastAPI >=0.143, async SQLAlchemy 2, asyncpg + psycopg (Alembic only), pydantic-settings >=2.16.
- Frontend React 19 + Vite 8 + Tailwind v4 + i18next + TanStack Query.

## Review Focus

The spec is silent on five input classes that are most likely to bite a real user. Each line names the input and the expected behaviour, then points to the task whose test pins it.

1. **Empty file upload** — the user uploads a 0-byte file. Expected: rejected at the API with 422 and a clear error message; the chunker never sees an empty string. → Task 6 (`test_upload_rejects_empty_file`).
2. **Re-indexing the same document** — the user uploads the same file twice. Expected: existing chunks with the same content-hash IDs are reused (idempotent upsert); the document's `version` bumps; no duplicate rows. → Task 7 (`test_index_is_idempotent`).
3. **Search with no index** — the user runs a query before any document is indexed. Expected: empty result list, 200, no exception; the chat page shows "no documents yet". → Task 9 (`test_search_empty_index`).
4. **PDF with no extractable text** — the user uploads a scanned PDF (image-only). Expected: rejected with a clear "no extractable text" message before the chunker runs; the document status is `failed` with reason `empty_after_parse`. → Task 6 (`test_upload_rejects_image_only_pdf`).
5. **Query that returns zero hits above the score floor** — the user asks something the corpus doesn't cover. Expected: the chat page shows "I could not find anything relevant" instead of an LLM-generated hallucination; the audit row records `ok=False, error=no_hits`. → Task 11 (`test_chat_handles_no_hits`).

---

### Task 1: Package skeleton + Settings + ROUTERS contract

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/pyproject.toml`
- Create: `packages/backend/cliver-playbook-app-rag/README.md`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/settings.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/routes.py` (empty ROUTERS list for now)

**Interfaces:**
- Produces: `cliver_playbook.app.rag.ROUTERS: list[APIRouter]` (empty for now, populated in Task 4)
- Produces: `cliver_playbook.app.rag.Settings` with a `rag: RagSettings` block carrying the five-stage config (chunker / embedder / retriever / reranker / llm) and the **identity-domain Settings inheritance** (RAG depends on `cliver-playbook-app-user`, so its Settings subclass UserSettings, exactly like the mcp package does).

- [ ] **Step 1: Write the failing test**

Create `packages/backend/cliver-playbook-app-rag/tests/test_package.py`:
```python
from cliver_playbook.app.rag import ROUTERS, Settings, get_settings, settings
from cliver_playbook.app.rag.settings import RagSettings


def test_settings_inherits_user_settings() -> None:
    s = Settings()
    # Inherits identity-domain fields
    assert hasattr(s, "oidc")
    assert hasattr(s, "oauth21")
    # Adds the rag block
    assert isinstance(s.rag, RagSettings)


def test_rag_settings_defaults() -> None:
    r = RagSettings()
    assert r.chunker == "recursive"
    assert r.embedder == "bge-m3"
    assert r.retriever == "pgvector-hybrid"
    assert r.reranker == "bge-reranker-v2-m3"
    assert r.llm == "stub"
    assert r.top_k == 20
    assert r.score_floor == 0.2


def test_routers_is_a_list() -> None:
    assert isinstance(ROUTERS, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_package.py -v`
Expected: FAIL (no such package).

- [ ] **Step 3: Write `pyproject.toml`**

Mirror the mcp package's pyproject (hatchling, src-layout, dev-mode-dirs=["src"], no `__init__.py` in `src/cliver_playbook/` or `src/cliver_playbook/app/`). Dependencies: `cliver-playbook-app-user`, `fastapi>=0.143.0`, `sqlalchemy>=2.0.36`, `pydantic>=2.0.0`, `pydantic-settings>=2.16.0`, `asyncpg>=0.30.0`, `psycopg[binary]>=3.2.0` (Alembic), `uvicorn>=0.31.1`, `langchain-text-splitters>=0.3.0`, `sentence-transformers>=3.0.0`, `FlagEmbedding>=1.2.0`, `rank-bm25>=0.2.2`, `unstructured[pdf]>=0.16.0`, `tree-sitter>=0.23.0`, `tree-sitter-languages>=1.10.0`, `openai>=1.40.0` (optional hosted embedder), `numpy>=1.26.0`. Dev: `pytest>=8.3.0`, `pytest-asyncio>=0.24.0`, `ruff>=0.8.0`.

- [ ] **Step 4: Write `__init__.py`**

```python
"""rag: the knowledge-base package — pluggable RAG over the identity stack."""
from cliver_playbook.app.rag.api.routes import ROUTERS
from cliver_playbook.app.rag.settings import Settings, get_settings, settings

__all__ = ["ROUTERS", "Settings", "get_settings", "settings"]
```

- [ ] **Step 5: Write `settings.py`**

`RagSettings(BaseModel)` with the 9 fields from the test, plus a `pgvector_index_lists: int = 100` knob and `chunk_size: int = 512`, `chunk_overlap: int = 64`. `Settings(UserSettings)` adds `rag: RagSettings = Field(default_factory=RagSettings)`. The lazy proxy mirrors mcp's pattern.

- [ ] **Step 6: Write `api/routes.py`**

```python
from fastapi import APIRouter
ROUTERS: list[APIRouter] = []
```

- [ ] **Step 7: Register the package in the workspace**

Add the new package to the root `pyproject.toml` `[tool.uv.workspace]` members and to the root `Makefile`'s `BACKEND_PACKAGES` glob. (The glob `packages/backend/cliver-playbook-app-*` already picks it up automatically — verify with `make help` and `make backend-test`.)

- [ ] **Step 8: Run test to verify it passes**

Run: `cd /Users/lgao/sources/cliver-project/mcp_x/cliver-playbook && uv sync && uv run --package cliver-playbook-app-rag pytest packages/backend/cliver-playbook-app-rag/tests/test_package.py -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/ pyproject.toml uv.lock
git commit -m "feat(rag): backend package skeleton, settings, empty ROUTERS contract"
```

---

### Task 2: Database schema + Alembic chain + pgvector extension

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/alembic/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/alembic/env.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/alembic/versions/0001_rag_initial.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/models/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/models/entities.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/models/base.py`

**Interfaces:**
- Produces: `Base` (SQLAlchemy declarative base, declared in `models/base.py`; imported by `alembic/env.py` for autogenerate support)
- Produces: tables `documents` and `chunks` (see Step 3 for the schema)
- Produces: `version_table="alembic_version_rag"` (own chain, never the default `alembic_version`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema.py`:
```python
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from cliver_playbook.app.rag.models.base import Base
from cliver_playbook.app.rag.models.entities import Chunk, Document


def test_document_columns() -> None:
    cols = {c.name for c in Document.__table__.columns}
    assert {"id", "title", "source_uri", "mime_type", "chunker_id",
            "embedder_id", "dim", "version", "created_at"}.issubset(cols)


def test_chunk_columns() -> None:
    cols = {c.name for c in Chunk.__table__.columns}
    assert {"id", "document_id", "ordinal", "text", "token_count",
            "metadata", "parent_id", "created_at"}.issubset(cols)
```
Add a runtime test that creates an in-memory SQLite engine (pgvector types are no-ops in SQLite — use `Column(..., nullable=True)` and `Text()` for the embedding column) and verifies the tables exist. Use `if "postgresql" in url.drivername: ... else: ...` in the model to switch types.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_schema.py -v`
Expected: FAIL (no module).

- [ ] **Step 3: Write `models/base.py`**

Mirror basic's `db/base.py` pattern. Use SQLAlchemy 2.0 declarative base.

- [ ] **Step 4: Write `models/entities.py`**

Two tables:

```python
class Document(Base):
    __tablename__ = "rag_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    source_uri: Mapped[str] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128))
    chunker_id: Mapped[str] = mapped_column(String(64))
    embedder_id: Mapped[str] = mapped_column(String(64))
    dim: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Chunk(Base):
    __tablename__ = "rag_chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("rag_documents.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Embedding lives in a separate table to keep this table fast; FK to chunk.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChunkEmbedding(Base):
    __tablename__ = "rag_chunk_embeddings"
    chunk_id: Mapped[str] = mapped_column(String(64), ForeignKey("rag_chunks.id", ondelete="CASCADE"), primary_key=True)
    # pgvector: VECTOR(1024). SQLite: Text fallback. Use SA literal_column or dialect-specific Column.
    embedding: Mapped[object] = mapped_column(...)  # see Step 4a
    sparse_lexical: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # for SPLADE / tsvector
    embedder_version: Mapped[str] = mapped_column(String(64))
```

For the `embedding` column, use a dialect-aware approach:
```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy import Column, Integer, String, Text
# The actual vector type lives in the migration (CREATE TABLE ... embedding vector(N));
# ORM-side, we use a placeholder type that round-trips through the DBAPI.
embedding = mapped_column(Vector(dim), nullable=True)  # use pgvector's SA type
```

Use `pgvector.sqlalchemy.Vector` from the `pgvector` package (the SQLAlchemy integration is in the `pgvector` distribution).

- [ ] **Step 5: Write `alembic/env.py`**

Mirror basic's env.py with `VERSION_TABLE = "alembic_version_rag"`, `target_metadata = Base.metadata`, and `_database_url()` from `cliver_playbook.app.rag.settings`.

- [ ] **Step 6: Write `alembic/versions/0001_rag_initial.py`**

First DDL: `CREATE EXTENSION IF NOT EXISTS vector;` (so the migration is the one place that requires the extension; the docker-compose change in Task 1's commit message notes this). Then `CREATE TABLE rag_documents (...)`, `CREATE TABLE rag_chunks (...)` with a GIN on `to_tsvector('english', text)` for BM25, `CREATE TABLE rag_chunk_embeddings (...)` with `embedding vector(1024)`. Add a HNSW index: `CREATE INDEX rag_chunks_hnsw ON rag_chunk_embeddings USING hnsw (embedding vector_cosine_ops);` (the dim is set at runtime by the embedder, so the migration uses 1024 and the model is configured to match — a future migration can ALTER if dim changes).

- [ ] **Step 7: Add a programmatic migration runner**

In `__init__.py` of the rag package, expose `run_migrations_online(url: str | None = None)` mirroring basic's pattern. The mcp package's `migrate.py` adds a `run_all_migrations()` that calls each package's. The plan's Task 12 extends that.

- [ ] **Step 8: Run test to verify it passes (SQLite)**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_schema.py -v`
Expected: PASS. (The test uses SQLite so pgvector is not loaded; the table-existence assertion holds because the ORM emits the right DDL.)

- [ ] **Step 9: Run migration against the dev database**

`make db-up` (Postgres in compose) then `cd packages/backend/cliver-playbook-app-rag && uv run python -c "from cliver_playbook.app.rag.alembic import run_migrations_online; run_migrations_online()"` — verify `alembic_version_rag` row appears, `\\d rag_documents` in psql shows the columns.

- [ ] **Step 10: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/
git commit -m "feat(rag): documents/chunks/embeddings schema, alembic chain, pgvector"
```

---

### Task 3: Permissions registration + audit wrapper

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/permissions.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/audit.py`
- Modify: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/__init__.py` to import `permissions` first (mcp pattern)

**Interfaces:**
- Produces: 5 permission codes registered into the identity catalog at import: `rag:documents:read`, `rag:documents:write`, `rag:search:read`, `rag:chat:read`, `rag:admin:read`
- Produces: `write_rag_audit(*, event, target, ok, args=None, extra=None) -> None` — best-effort wrapper over user-management's `write_audit`

- [ ] **Step 1: Write the failing test**

```python
from cliver_playbook.app.user.auth.permissions import permission_codes


def test_rag_permissions_registered() -> None:
    codes = set(permission_codes())
    for expected in (
        "rag:documents:read",
        "rag:documents:write",
        "rag:search:read",
        "rag:chat:read",
        "rag:admin:read",
    ):
        assert expected in codes, f"missing permission code: {expected}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_permissions.py -v`
Expected: FAIL (codes not registered).

- [ ] **Step 3: Write `permissions.py`**

Mirror `cliver_playbook.app.mcp.permissions`:
```python
from cliver_playbook.app.user.auth.permissions import Permission, register_permission_codes

_PERMISSIONS = (
    Permission(code="rag:documents:read", name="Read RAG documents", group="rag"),
    Permission(code="rag:documents:write", name="Upload/index RAG documents", group="rag"),
    Permission(code="rag:search:read", name="Run RAG search", group="rag"),
    Permission(code="rag:chat:read", name="Run RAG chat", group="rag"),
    Permission(code="rag:admin:read", name="RAG admin: list all documents", group="rag"),
)

register_permission_codes(_PERMISSIONS)
```

- [ ] **Step 4: Modify `__init__.py`**

Add `from cliver_playbook.app.rag import permissions  # noqa: F401` BEFORE the api.routes import (mcp pattern). The test then sees the codes registered.

- [ ] **Step 5: Write `audit.py`**

```python
async def write_rag_audit(*, event: str, target: str, ok: bool, args: dict | None = None,
                          extra: dict | None = None) -> None:
    """Best-effort wrapper; never raises."""
    try:
        from cliver_playbook.app.basic.db.session import open_session
        from cliver_playbook.app.user.auth.audit import write_audit
        async with open_session() as session:
            await write_audit(
                session=session,
                event=f"rag.{event}",
                target=target,
                ok=ok,
                detail={"args": args or {}, **(extra or {})},
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("cliver_playbook.app.rag.audit").warning("rag audit write failed: %s", exc)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_permissions.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/permissions.py \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/audit.py \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/__init__.py \
        packages/backend/cliver-playbook-app-rag/tests/test_permissions.py
git commit -m "feat(rag): register 5 rag:* permission codes, audit wrapper"
```

---

### Task 4: Chunker protocol + 3 default chunkers

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/base.py` (Protocol, Document, Chunk, SourceOffset)
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/recursive.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/markdown.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/code.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/pdf.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/registry.py`

**Interfaces (the seam):**
```python
class Document(BaseModel):
    id: str           # source URI / file path
    source_version: str
    mime_type: str
    raw: str | bytes
    metadata: dict = {}

class SourceOffset(BaseModel):
    start: int
    end: int
    unit: Literal["char", "byte", "token"] = "char"

class Chunk(BaseModel):
    id: str           # sha256 of (document.id, source_version, ordinal, text)
    text: str
    metadata: dict
    parent_id: str | None
    source_offset: SourceOffset

class Chunker(Protocol):
    name: str
    version: str
    def split(self, doc: Document, *, chunk_size: int = 512, chunk_overlap: int = 64) -> list[Chunk]: ...
```

`registry.get(name: str) -> Chunker` returns one of `RecursiveChunker`, `MarkdownChunker`, `CodeChunker`, `PdfChunker`. The recursive is the default.

- [ ] **Step 1: Write the failing test**

```python
import hashlib
from cliver_playbook.app.rag.chunking import Document, get_chunker
from cliver_playbook.app.rag.chunking.registry import registry


def test_registry_has_four_chunkers() -> None:
    assert set(registry.names()) == {"recursive", "markdown", "code", "pdf"}


def test_recursive_chunker_idempotent() -> None:
    c = get_chunker("recursive")
    text = "Sentence one. Sentence two. " * 200
    doc = Document(id="a", source_version="v1", mime_type="text/plain", raw=text)
    chunks_a = c.split(doc, chunk_size=200, chunk_overlap=20)
    chunks_b = c.split(doc, chunk_size=200, chunk_overlap=20)
    assert [ch.id for ch in chunks_a] == [ch.id for ch in chunks_b]
    # ID is content-hash, not UUID
    expected = hashlib.sha256(f"a|v1|0|{chunks_a[0].text}".encode()).hexdigest()[:32]
    assert chunks_a[0].id == expected


def test_markdown_chunker_preserves_header_metadata() -> None:
    c = get_chunker("markdown")
    md = "# H1\nintro\n## H2\nbody\n"
    doc = Document(id="m", source_version="v1", mime_type="text/markdown", raw=md)
    chunks = c.split(doc, chunk_size=128, chunk_overlap=0)
    assert any("H1" in ch.metadata.get("section_path", []) for ch in chunks)
    assert any("H2" in ch.metadata.get("section_path", []) for ch in chunks)


def test_code_chunker_uses_tree_sitter() -> None:
    c = get_chunker("code")
    py = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    doc = Document(id="c", source_version="v1", mime_type="text/x-python", raw=py)
    chunks = c.split(doc, chunk_size=64, chunk_overlap=0)
    # Two functions, two chunks
    assert len(chunks) == 2
    assert "def a" in chunks[0].text
    assert "def b" in chunks[1].text


def test_pdf_chunker_uses_unstructured() -> None:
    # Mock the unstructured partition so the test doesn't need a real PDF
    from unittest.mock import patch
    c = get_chunker("pdf")
    with patch("cliver_playbook.app.rag.chunking.pdf._partition") as mock_partition:
        from unstructured.documents.elements import Title, NarrativeText
        mock_partition.return_value = [
            Title("First Section"),
            NarrativeText("Body of the first section."),
        ]
        doc = Document(id="p", source_version="v1", mime_type="application/pdf", raw=b"%PDF-fake")
        chunks = c.split(doc, chunk_size=128, chunk_overlap=0)
        assert len(chunks) == 2
        assert chunks[0].metadata.get("element_type") == "Title"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_chunking.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `chunking/base.py`**

The Protocol + Document + Chunk + SourceOffset as above. Use `typing.Protocol` for the structural type.

- [ ] **Step 4: Write `chunking/recursive.py`**

Wraps `langchain_text_splitters.RecursiveCharacterTextSplitter` with `chunk_size` and `chunk_overlap`. Compute the ID as `sha256(f"{doc.id}|{doc.source_version}|{ordinal}|{text}")[:32]`. `source_offset` is the char range the chunker reports.

- [ ] **Step 5: Write `chunking/markdown.py`**

`MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")])` then recursive on the bodies. Header metadata `section_path` is the path of headers. For small documents (under chunk_size) the whole doc is one chunk with all headers in `section_path`.

- [ ] **Step 6: Write `chunking/code.py`**

`RecursiveCharacterTextSplitter.from_language(Language.PYTHON)` from langchain; treat `text/x-python`, `text/x-javascript`, `text/x-typescript` (and similar) the same way. The "tree-sitter" in the research note is a langchain internal here — the same AST-aware splitting.

- [ ] **Step 7: Write `chunking/pdf.py`**

`unstructured.partition.pdf.partition_pdf(raw_bytes, strategy="fast")` returns elements. Each element becomes a chunk with `metadata.element_type` set. If the result is empty, raise `EmptyDocumentError` (a domain exception; caught at the upload endpoint, mapped to 422 with reason `empty_after_parse`). Tests mock the partition call.

- [ ] **Step 8: Write `chunking/registry.py`**

`ChunkerRegistry` with `register(name, factory)`, `get(name) -> Chunker`, `names() -> set[str]`. Pre-register the four chunkers above at module import. `get_chunker(name) -> Chunker` is a module-level helper.

- [ ] **Step 9: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_chunking.py -v`
Expected: PASS (5 tests).

- [ ] **Step 10: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/chunking/ \
        packages/backend/cliver-playbook-app-rag/tests/test_chunking.py
git commit -m "feat(rag): Chunker protocol + recursive/markdown/code/pdf implementations"
```

---

### Task 5: Embedder protocol + BGE-M3 + stub embedder

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/embedding/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/embedding/base.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/embedding/bge_m3.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/embedding/stub.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/embedding/registry.py`

**Interfaces (the seam):**
```python
class Embedder(Protocol):
    id: str           # "bge-m3@<commit>" or "stub@1.0"
    dim: int
    max_input_tokens: int
    supports_query_document_modes: bool

    def embed(self, texts: list[str], *, mode: str = "document") -> list[list[float]]: ...
    def estimate_tokens(self, text: str) -> int: ...
```

`registry.get(name: str) -> Embedder` returns the requested embedder. Default is `bge-m3`.

- [ ] **Step 1: Write the failing test**

```python
import math
import numpy as np
from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.embedding.registry import registry


def test_registry_has_bge_m3_and_stub() -> None:
    names = registry.names()
    assert "bge-m3" in names
    assert "stub" in names


def test_stub_embedder_is_deterministic_unit_norm() -> None:
    e = get_embedder("stub")
    a = e.embed(["hello world"], mode="document")[0]
    b = e.embed(["hello world"], mode="document")[0]
    assert a == b
    norm = math.sqrt(sum(x * x for x in a))
    assert abs(norm - 1.0) < 1e-5
    assert e.dim == 64
    assert "stub" in e.id


def test_bge_m3_embedder_dim() -> None:
    e = get_embedder("bge-m3")
    # Don't run the actual model in unit tests — only assert metadata
    assert e.dim == 1024
    assert e.supports_query_document_modes is True
    assert e.id.startswith("bge-m3@") or e.id.startswith("BAAI/bge-m3@")


def test_stub_estimate_tokens() -> None:
    e = get_embedder("stub")
    assert e.estimate_tokens("hello world") == 2  # words
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_embedding.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `embedding/base.py`**

The Protocol + an `Embedding` dataclass (`{vector, model_id, dim}`).

- [ ] **Step 4: Write `embedding/stub.py`**

`StubEmbedder` with `dim=64`. Embedding is `np.random.RandomState(hash(text) & 0xFFFFFFFF).randn(dim)`, L2-normalized. Deterministic per text. `estimate_tokens` returns word count. `id = "stub@1.0"`.

- [ ] **Step 5: Write `embedding/bge_m3.py`**

`BgeM3Embedder` wraps `FlagEmbedding.BGEM3FlagModel.from_finetuned("BAAI/bge-m3", use_fp16=False, devices="cpu")`. Lazy-load the model on first `embed` call (so the package can be imported without GPU/RAM). `id` reads the model's HF commit hash at load time. `dim=1024`, `supports_query_document_modes=True`. `estimate_tokens` uses a simple word count (BGE-M3's actual tokenizer is complex; for the upload preview, word count is close enough).

- [ ] **Step 6: Write `embedding/registry.py`**

Same shape as the chunker registry.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_embedding.py -v`
Expected: PASS (4 tests). The `bge-m3` test does NOT call `embed()`; it only checks metadata, so no model download is needed.

- [ ] **Step 8: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/embedding/ \
        packages/backend/cliver-playbook-app-rag/tests/test_embedding.py
git commit -m "feat(rag): Embedder protocol + BGE-M3 (lazy) + stub for offline dev"
```

---

### Task 6: Upload endpoint with per-stage selection + preview

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/documents.py`
- Modify: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/routes.py`

**Interfaces:**
- Produces: `POST /api/v1/rag/documents/upload` — multipart upload; form fields `chunker`, `embedder`, `chunk_size`, `chunk_overlap`, `title`. Returns 201 with `{document_id, chunk_count, preview_chunks: [{ordinal, text, token_count, chunk_id_prefix}]}`.
- Produces: `POST /api/v1/rag/documents/{document_id}/index` — commits the previewed chunks. Idempotent: if chunks already exist with the same content-hash IDs, no-op.

- [ ] **Step 1: Write the failing test**

```python
import io
import pytest
from httpx import AsyncClient, ASGITransport
from cliver_playbook.app.rag.app import create_app
from cliver_playbook.app.rag.settings import Settings


@pytest.fixture
async def client():
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")  # type: ignore[arg-type]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_upload_creates_document_with_chunks(client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world. " * 50), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["chunk_count"] > 0
    assert len(body["preview_chunks"]) == body["chunk_count"]


async def test_upload_rejects_empty_file(client: AsyncClient) -> None:
    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub"}
    r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    assert r.status_code == 422
    assert "empty" in r.json()["detail"].lower()


async def test_upload_rejects_unknown_chunker(client: AsyncClient) -> None:
    files = {"file": ("hello.txt", io.BytesIO(b"Hello world."), "text/plain")}
    data = {"chunker": "no-such-chunker", "embedder": "stub"}
    r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    assert r.status_code == 422


async def test_upload_rejects_image_only_pdf(client: AsyncClient) -> None:
    from unittest.mock import patch
    files = {"file": ("scan.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")}
    data = {"chunker": "pdf", "embedder": "stub"}
    with patch("cliver_playbook.app.rag.chunking.pdf._partition", return_value=[]):
        r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    assert r.status_code == 422
    assert "no extractable text" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_upload.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `api/documents.py`**

Two endpoints:

```python
router = APIRouter(prefix="/api/v1/rag/documents", tags=["rag-documents"])

@router.post("/upload", status_code=201)
async def upload(...) -> dict: ...
@router.post("/{document_id}/index", status_code=200)
async def index(...) -> dict: ...
```

The upload endpoint:
1. Reads the file. If 0 bytes → 422 `empty_file`.
2. Builds a `Document` from the file (mime_type from the upload, source_uri from the filename).
3. Resolves the chunker from the form value. If unknown → 422.
4. Calls `chunker.split(doc, chunk_size=..., chunk_overlap=...)`. If PDF + empty partition → 422 `no_extractable_text`.
5. Persists a `rag_documents` row with status=`pending`, chunker_id, embedder_id, dim (looked up from the embedder), chunk_count, and the `rag_chunks` rows.
6. Returns the document id + the chunk list (truncated to 50 for the preview; full list is in the DB).

The index endpoint:
1. Looks up the document. If status=`indexed` → 200 no-op.
2. For each chunk, gets an embedding from the embedder. Upserts into `rag_chunk_embeddings`.
3. Updates `rag_chunks.metadata_json` with `{"ordinal": ..., "token_count": ..., "section_path": ...}`.
4. Updates `rag_documents.status="indexed"`, `chunk_count=...`.
5. Writes a `rag.document.index` audit row.
6. Returns `{document_id, status: "indexed", chunk_count}`.

- [ ] **Step 4: Add auth + permission gate**

`@router.post("/upload", dependencies=[Security(require_perm, scopes=["rag:documents:write"])])`. `require_perm` is the existing identity dependency (imported from `cliver_playbook.app.user.auth.dependencies`). Same for `index` and `read` endpoints (Task 7).

- [ ] **Step 5: Add the router to `api/routes.py`**

```python
from cliver_playbook.app.rag.api import documents
ROUTERS: list[APIRouter] = [documents.router]
```

- [ ] **Step 6: Wire the test app with SQLite + a memory audit shim**

The fixture in Step 1 uses a SQLite test DB. The `create_app(settings)` for tests builds an app with `rag_documents` / `rag_chunks` / `rag_chunk_embeddings` tables created via `Base.metadata.create_all` (since alembic isn't run in the test). The audit wrapper silently no-ops when the user table isn't present.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_upload.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/ \
        packages/backend/cliver-playbook-app-rag/tests/test_upload.py
git commit -m "feat(rag): upload + index endpoints with per-stage selection and preview"
```

---

### Task 7: Document list/read endpoints + idempotent re-index

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/documents.py` (extend)
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/services/documents.py`
- Create: `packages/backend/cliver-playbook-app-rag/tests/test_documents_crud.py`

**Interfaces:**
- Produces: `GET /api/v1/rag/documents` — list user's documents (gated `rag:documents:read`)
- Produces: `GET /api/v1/rag/documents/{id}` — read one document
- Produces: `GET /api/v1/rag/documents/{id}/chunks` — read the chunks of a document

- [ ] **Step 1: Write the failing test**

```python
import io
import pytest
from httpx import AsyncClient, ASGITransport
from cliver_playbook.app.rag.app import create_app
from cliver_playbook.app.rag.settings import Settings


@pytest.fixture
async def client():
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")  # type: ignore[arg-type]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _upload_and_index(client: AsyncClient, content: bytes, name: str = "x.txt") -> str:
    files = {"file": (name, io.BytesIO(content), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    assert r.status_code == 201, r.text
    doc_id = r.json()["document_id"]
    r2 = await client.post(f"/api/v1/rag/documents/{doc_id}/index")
    assert r2.status_code == 200
    return doc_id


async def test_list_documents(client: AsyncClient) -> None:
    await _upload_and_index(client, b"Hello. " * 50)
    r = await client.get("/api/v1/rag/documents")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["chunker_id"] == "recursive"
    assert items[0]["embedder_id"] == "stub"
    assert items[0]["status"] == "indexed"


async def test_get_document_chunks(client: AsyncClient) -> None:
    doc_id = await _upload_and_index(client, b"Hello. " * 50)
    r = await client.get(f"/api/v1/rag/documents/{doc_id}/chunks")
    assert r.status_code == 200
    chunks = r.json()["items"]
    assert len(chunks) > 0
    assert all("text" in c and "ordinal" in c for c in chunks)


async def test_index_is_idempotent(client: AsyncClient) -> None:
    """Re-uploading the same file yields the same document id (content-hash),
    and re-indexing is a no-op."""
    content = b"The same content. " * 30
    doc_id_a = await _upload_and_index(client, content, name="same.txt")
    doc_id_b = await _upload_and_index(client, content, name="same.txt")
    assert doc_id_a == doc_id_b
    # chunks count unchanged
    r = await client.get(f"/api/v1/rag/documents/{doc_id_a}/chunks")
    assert r.status_code == 200
    chunks_a = r.json()["items"]
    r2 = await client.post(f"/api/v1/rag/documents/{doc_id_a}/index")
    assert r2.status_code == 200
    r3 = await client.get(f"/api/v1/rag/documents/{doc_id_a}/chunks")
    assert r3.json()["items"] == chunks_a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_documents_crud.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the three GET endpoints to `documents.py`**

```python
@router.get("", response_model=DocumentList)
async def list_documents(...) -> DocumentList: ...
@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: str, ...) -> DocumentRead: ...
@router.get("/{document_id}/chunks", response_model=ChunkList)
async def get_chunks(document_id: str, ...) -> ChunkList: ...
```

- [ ] **Step 4: Add `services/documents.py`**

Pure-data access functions: `list_documents_for_user(db, user_id)`, `get_document(db, document_id)`, `list_chunks(db, document_id)`. No business logic; just queries. The routers call them.

- [ ] **Step 5: Implement idempotency**

In the upload endpoint, the document id is `sha256(source_uri + content_sha256)[:32]`. The chunk ids are `sha256(document_id + source_version + ordinal + text)[:32]`. Re-uploading the same content upserts by id. Re-indexing is a no-op because the chunks already exist with the same id and the embedder is deterministic.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_documents_crud.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/documents.py \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/services/ \
        packages/backend/cliver-playbook-app-rag/tests/test_documents_crud.py
git commit -m "feat(rag): list/read documents endpoints, content-hash idempotency"
```

---

### Task 8: Retriever protocol + pgvector hybrid + BM25 fallback

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/retrieval/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/retrieval/base.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/retrieval/pgvector_hybrid.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/retrieval/bm25_only.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/retrieval/registry.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/search.py`

**Interfaces (the seam):**
```python
class Hit(BaseModel):
    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    score: float
    metadata: dict = {}

class Query(BaseModel):
    text: str
    top_k: int = 20
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"

class Retriever(Protocol):
    name: str
    def retrieve(self, q: Query) -> list[Hit]: ...
    def upsert(self, chunk_id: str, text: str, embedding: list[float]) -> None: ...
    def delete(self, chunk_ids: list[str]) -> None: ...
```

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import MagicMock
from cliver_playbook.app.rag.retrieval import get_retriever, Query, Hit
from cliver_playbook.app.rag.retrieval.registry import registry


def test_registry_has_pgvector_and_bm25() -> None:
    names = registry.names()
    assert "pgvector-hybrid" in names
    assert "bm25-only" in names


def test_bm25_only_retriever_works_offline() -> None:
    """The bm25-only retriever must work without pgvector (test in SQLite)."""
    r = get_retriever("bm25-only")
    r.upsert("c1", "the quick brown fox", [0.0] * 4)
    r.upsert("c2", "lazy dog sleeps", [0.0] * 4)
    hits = r.retrieve(Query(text="quick fox", top_k=5))
    assert len(hits) >= 1
    assert hits[0].chunk_id == "c1"
    assert hits[0].score > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_retrieval.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `retrieval/base.py`**

Protocol + Hit + Query dataclasses.

- [ ] **Step 4: Write `retrieval/bm25_only.py`**

`Bm25OnlyRetriever` holds chunks in an in-memory `rank_bm25.BM25Okapi` index, indexed by lower-cased words. `upsert` and `delete` mutate the in-memory list (good enough for tests and offline; not for production). `retrieve` scores with BM25 and returns `Hit` rows.

- [ ] **Step 5: Write `retrieval/pgvector_hybrid.py`**

`PgvectorHybridRetriever`:
- `retrieve`: runs two SQL queries and fuses with RRF.
  - Dense: `SELECT chunk_id, document_id, ordinal, text, 1 - (embedding <=> $1) AS score FROM rag_chunk_embeddings ORDER BY embedding <=> $1 LIMIT $2` (uses `pgvector` operators).
  - Sparse: `SELECT chunk_id, document_id, ordinal, text, ts_rank_cd(to_tsvector('english', text), plainto_tsquery('english', $1)) AS score FROM rag_chunks WHERE to_tsvector('english', text) @@ plainto_tsquery('english', $1) ORDER BY score DESC LIMIT $2`.
  - RRF: `combined_score = sum(1 / (60 + rank))` over the two lists. Sort by combined score DESC. Return top_k.
- `upsert`: insert/update the `rag_chunk_embeddings` row; update the tsvector column (trigger or computed).
- `delete`: delete by chunk_id.
- The actual SQL is generated with SQLAlchemy 2.0 `text()` and a bindparam for the embedding (use `pgvector`'s `to_pgvector` adapter).

- [ ] **Step 6: Write `retrieval/registry.py`**

Same pattern as the others. The default is `bm25-only` in tests (no pgvector available) and `pgvector-hybrid` in production (set by `Settings.rag.retriever`).

- [ ] **Step 7: Write `api/search.py`**

```python
router = APIRouter(prefix="/api/v1/rag/search", tags=["rag-search"])

@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest, ...) -> SearchResponse: ...
```

`SearchRequest = {query: str, top_k: int = 20}`. The endpoint calls `get_retriever(settings.rag.retriever).retrieve(...)` and returns the hits.

- [ ] **Step 8: Add the router to `api/routes.py`**

- [ ] **Step 9: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_retrieval.py -v`
Expected: PASS (2 tests).

- [ ] **Step 10: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/retrieval/ \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/search.py \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/routes.py \
        packages/backend/cliver-playbook-app-rag/tests/test_retrieval.py
git commit -m "feat(rag): Retriever protocol + bm25-only + pgvector-hybrid + search endpoint"
```

---

### Task 9: Search endpoint + empty-index handling

**Files:**
- Extend: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/search.py`
- Create: `packages/backend/cliver-playbook-app-rag/tests/test_search.py`

**Interfaces:**
- Produces: `POST /api/v1/rag/search` — body `{query, top_k}`. Returns `{hits: [{chunk_id, document_id, ordinal, text, score, metadata}]}`. Empty list if no index.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from httpx import AsyncClient, ASGITransport
from cliver_playbook.app.rag.app import create_app
from cliver_playbook.app.rag.settings import Settings


@pytest.fixture
async def client():
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")  # type: ignore[arg-type]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_search_empty_index(client: AsyncClient) -> None:
    r = await client.post("/api/v1/rag/search", json={"query": "anything", "top_k": 5})
    assert r.status_code == 200
    assert r.json()["hits"] == []


async def test_search_returns_indexed_chunks(client: AsyncClient) -> None:
    # Upload + index a document
    import io
    files = {"file": ("x.txt", io.BytesIO(b"The quick brown fox. " * 30), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "64", "chunk_overlap": "0"}
    r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    doc_id = r.json()["document_id"]
    await client.post(f"/api/v1/rag/documents/{doc_id}/index")
    # Search
    r2 = await client.post("/api/v1/rag/search", json={"query": "quick fox", "top_k": 5})
    assert r2.status_code == 200
    hits = r2.json()["hits"]
    assert len(hits) >= 1
    assert any("quick" in h["text"] or "fox" in h["text"] for h in hits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_search.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the gate + retriever call**

The endpoint reads the configured retriever, calls `retrieve`, and returns the hits as JSON. Empty list on no index is the normal path — the retriever returns an empty list, the endpoint returns `{hits: []}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_search.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/search.py \
        packages/backend/cliver-playbook-app-rag/tests/test_search.py
git commit -m "feat(rag): /search endpoint with empty-index handling"
```

---

### Task 10: Reranker protocol + BGE-reranker-v2-m3 + noop

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/reranking/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/reranking/base.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/reranking/bge.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/reranking/noop.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/reranking/registry.py`

**Interfaces (the seam):**
```python
class Reranker(Protocol):
    name: str
    model_id: str
    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]: ...
```

- [ ] **Step 1: Write the failing test**

```python
from cliver_playbook.app.rag.retrieval.base import Hit
from cliver_playbook.app.rag.reranking import get_reranker
from cliver_playbook.app.rag.reranking.registry import registry


def test_registry_has_bge_and_noop() -> None:
    names = registry.names()
    assert "bge-reranker-v2-m3" in names
    assert "noop" in names


def test_noop_reranker_preserves_order() -> None:
    r = get_reranker("noop")
    hits = [
        Hit(chunk_id="a", document_id="d", ordinal=0, text="a", score=0.9, metadata={}),
        Hit(chunk_id="b", document_id="d", ordinal=1, text="b", score=0.5, metadata={}),
    ]
    out = r.rerank("q", hits)
    assert [h.chunk_id for h in out] == ["a", "b"]


def test_noop_reranker_top_k_truncates() -> None:
    r = get_reranker("noop")
    hits = [Hit(chunk_id=str(i), document_id="d", ordinal=i, text="t", score=1.0 - i*0.1, metadata={}) for i in range(10)]
    out = r.rerank("q", hits, top_k=3)
    assert len(out) == 3


def test_bge_reranker_metadata() -> None:
    r = get_reranker("bge-reranker-v2-m3")
    # Don't call rerank in unit test (no model download); just check metadata
    assert "bge-reranker" in r.model_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_reranking.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `reranking/base.py`**

Protocol + helpers.

- [ ] **Step 4: Write `reranking/noop.py`**

Identity rerank; `top_k` truncates.

- [ ] **Step 5: Write `reranking/bge.py`**

`BgeRerankerV2M3` wraps `FlagEmbedding.BGERerankFlagModel` (or `FlagEmbedding.reranker.FlagReranker` for the v2-m3 model). Lazy-load on first call. `model_id` reads from HF API at load time. Synchronous `rerank(query, hits)` → `FlagReranker.compute_score([(query, h.text) for h in hits])` → sort by score DESC → return reordered hits. `top_k` truncates.

- [ ] **Step 6: Write `reranking/registry.py`**

- [ ] **Step 7: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_reranking.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/reranking/ \
        packages/backend/cliver-playbook-app-rag/tests/test_reranking.py
git commit -m "feat(rag): Reranker protocol + bge-reranker-v2-m3 (lazy) + noop"
```

---

### Task 11: LLM protocol + stub generator + chat endpoint

**Files:**
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/llm/__init__.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/llm/base.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/llm/stub.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/llm/registry.py`
- Create: `packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/chat.py`

**Interfaces (the seam):**
```python
class LLM(Protocol):
    name: str
    model_id: str
    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str: ...
```

The chat endpoint:
1. Retriever retrieves top_k.
2. Reranker reranks.
3. If `top_hits == 0` → return `{answer: "I could not find anything relevant.", citations: []}`, audit `ok=False, error=no_hits`.
4. Build a prompt: "Answer the question using ONLY the context. Cite each claim as [chunk_id].". The stub ignores the prompt and returns `"[stub] Based on the top {n} chunks:\n\n" + "\n\n---\n\n".join(h.text for h in hits)`.
5. Audit `rag.chat.run` with the question, hit count, model id.

- [ ] **Step 1: Write the failing test**

```python
import io
import pytest
from httpx import AsyncClient, ASGITransport
from cliver_playbook.app.rag.app import create_app
from cliver_playbook.app.rag.settings import Settings


@pytest.fixture
async def client():
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")  # type: ignore[arg-type]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _index(client, text: str) -> str:
    files = {"file": ("x.txt", io.BytesIO(text.encode()), "text/plain")}
    data = {"chunker": "recursive", "embedder": "stub", "chunk_size": "128", "chunk_overlap": "0"}
    r = await client.post("/api/v1/rag/documents/upload", files=files, data=data)
    doc_id = r.json()["document_id"]
    await client.post(f"/api/v1/rag/documents/{doc_id}/index")
    return doc_id


async def test_chat_handles_no_hits(client: AsyncClient) -> None:
    r = await client.post("/api/v1/rag/chat", json={"question": "anything"})
    assert r.status_code == 200
    body = r.json()
    assert "could not find" in body["answer"].lower()
    assert body["citations"] == []


async def test_chat_with_hits_returns_stub_answer(client: AsyncClient) -> None:
    await _index(client, "The quick brown fox. " * 30)
    r = await client.post("/api/v1/rag/chat", json={"question": "what does the doc say about foxes?"})
    assert r.status_code == 200
    body = r.json()
    assert "quick" in body["answer"] or "fox" in body["answer"]
    assert len(body["citations"]) >= 1
    assert all("chunk_id" in c for c in body["citations"])


async def test_chat_audit_written(client: AsyncClient) -> None:
    # The audit row's existence is asserted in a separate audit test
    await _index(client, "Hello world. " * 30)
    r = await client.post("/api/v1/rag/chat", json={"question": "hello?"})
    assert r.status_code == 200
    # If the test got here, no exception was raised writing the audit row
    assert r.json()["model_id"] == "stub@1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_chat.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `llm/base.py`**

Protocol.

- [ ] **Step 4: Write `llm/stub.py`**

`StubLLM` returns the chunks verbatim with a banner. `name="stub"`, `model_id="stub@1.0"`. Used as the default.

- [ ] **Step 5: Write `llm/registry.py`**

- [ ] **Step 6: Write `api/chat.py`**

```python
@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, ...) -> ChatResponse: ...
```

The endpoint composes retriever + reranker + llm in one request. Returns `{answer, citations: [{chunk_id, document_id, ordinal, score, text_preview}], model_id, hits_used, no_hits: bool}`.

- [ ] **Step 7: Add the router to `api/routes.py`**

- [ ] **Step 8: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-rag && uv run pytest tests/test_chat.py -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Commit**

```bash
git add packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/llm/ \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/chat.py \
        packages/backend/cliver-playbook-app-rag/src/cliver_playbook/app/rag/api/routes.py \
        packages/backend/cliver-playbook-app-rag/tests/test_chat.py
git commit -m "feat(rag): LLM protocol + stub + chat endpoint with no-hits handling"
```

---

### Task 12: Compose into mcp + root wiring + ADR

**Files:**
- Modify: `packages/backend/cliver-playbook-app-mcp/src/cliver_playbook/app/mcp/app.py` (import + use `rag.ROUTERS`)
- Modify: `packages/backend/cliver-playbook-app-mcp/src/cliver_playbook/app/mcp/migrate.py` (call `run_all_migrations()` includes rag)
- Modify: `packages/backend/cliver-playbook-app-mcp/pyproject.toml` (add `cliver-playbook-app-rag` dep)
- Create: `adr/0018-rag-module-architecture.md`

- [ ] **Step 1: Write the failing test**

In `packages/backend/cliver-playbook-app-mcp/tests/test_composition.py`:
```python
from cliver_playbook.app.mcp import create_app


def test_rag_routers_present() -> None:
    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert any(p.startswith("/api/v1/rag/documents") for p in paths)
    assert any(p == "/api/v1/rag/search" or p.startswith("/api/v1/rag/search") for p in paths)
    assert any(p == "/api/v1/rag/chat" or p.startswith("/api/v1/rag/chat") for p in paths)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/backend/cliver-playbook-app-mcp && uv run pytest tests/test_composition.py -v`
Expected: FAIL (no rag routes).

- [ ] **Step 3: Add `cliver-playbook-app-rag` to mcp's `pyproject.toml`**

- [ ] **Step 4: Update `mcp/app.py` to import + use rag routers**

```python
from cliver_playbook.app.rag.api.routes import ROUTERS as RAG_ROUTERS
...
for router in [*BASIC_ROUTERS, *USER_ROUTERS, *RAG_ROUTERS, *MCP_ROUTERS]:
    app.include_router(router)
```

- [ ] **Step 5: Update `mcp/migrate.py` to call rag's migration**

```python
from cliver_playbook.app.rag.alembic import run_migrations_online as rag_migrate
...
def run_all_migrations() -> None:
    basic_migrate()
    user_migrate()
    rag_migrate()
```

- [ ] **Step 6: Write ADR 0018**

```markdown
# ADR-0018: RAG knowledge-base module architecture

**Status:** Accepted (2026-10-18)
**Context:** the cliver-playbook library's RAG capability — see the spec at
docs/superpowers/specs/2026-10-18-rag-module-design.md.

## Decision

(… the protocol shapes, defaults, idempotency rules, audit policy, and the
"why this lands in the playbook" rationale from the spec, condensed. Each
rule ties to a task in the implementation plan that pins it.)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd packages/backend/cliver-playbook-app-mcp && uv run pytest tests/test_composition.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full backend test suite**

Run: `cd /Users/lgao/sources/cliver-project/mcp_x/cliver-playbook && make backend-test`
Expected: PASS (basic 16 + user 76 + mcp 58 + rag ~25 = ~175 tests).

- [ ] **Step 9: Run `make backend-lint`**

Expected: ruff ×4 packages all green.

- [ ] **Step 10: Live smoke**

- `make db-up` (Postgres with pgvector).
- `make db-init` (apply basic + user + rag chains).
- `make backend-start` (composed app on :8000).
- `curl http://127.0.0.1:8000/api/v1/rag/documents` → 401 (no token) — proves the route is registered and gated.
- `curl -X POST http://127.0.0.1:8000/api/v1/rag/search` → 401.

- [ ] **Step 11: Commit**

```bash
git add packages/backend/cliver-playbook-app-mcp/ adr/0018-rag-module-architecture.md
git commit -m "feat(mcp): compose rag package + ADR 0018"
```

---

### Task 13: Frontend package + RAG dev shell + live end-to-end

**Files:**
- Create: `packages/frontend/cliver-playbook-app-rag/package.json` (source-only, ADR-0008, deep paths with extensions)
- Create: `packages/frontend/cliver-playbook-app-rag/tsconfig.json`
- Create: `packages/frontend/cliver-playbook-app-rag/.oxlintrc.json`
- Create: `packages/frontend/cliver-playbook-app-rag/src/index.ts` (barrel)
- Create: `packages/frontend/cliver-playbook-app-rag/src/routes.tsx` (`ragRoutes` + `ragStandaloneRoutes`)
- Create: `packages/frontend/cliver-playbook-app-rag/src/nav.ts` (`ragNavItems`)
- Create: `packages/frontend/cliver-playbook-app-rag/src/locales/{en,zh}.json` + `index.ts` (export `ragTranslations`)
- Create: `packages/frontend/cliver-playbook-app-rag/src/api/rag.ts` (typed wrappers for upload / list / get / chunks / index / search / chat)
- Create: `packages/frontend/cliver-playbook-app-rag/src/pages/RagDocumentsPage.tsx` (upload form + chunker/embedder dropdowns + preview + index button + list)
- Create: `packages/frontend/cliver-playbook-app-rag/src/pages/RagChatPage.tsx` (question input + answer + citations)
- Create: `packages/frontend/cliver-playbook-app-rag/src/pages/admin/RagAdminPage.tsx` (admin list of all documents, gated)
- Create: `packages/frontend/cliver-playbook-app-rag/src/components/ChunkPreview.tsx`
- Create: `packages/frontend/cliver-playbook-app-rag/src/components/CitationBadge.tsx`
- Create: `packages/frontend/cliver-playbook-app-rag/src/components/StageSelector.tsx` (the chunker/embedder picker)
- Create: `packages/frontend/cliver-playbook-app-rag/README.md`
- Create: `packages/frontend/cliver-playbook-app-rag/dev/` (dev shell, same shape as mcp/user dev shells)
- Modify: `packages/frontend/cliver-playbook-app-mcp/dev/src/App.tsx` to add rag routes
- Modify: `packages/frontend/cliver-playbook-app-mcp/dev/src/main.tsx` to register rag translations
- Modify: `packages/frontend/cliver-playbook-app-mcp/dev/src/index.css` to add the rag dev shell's `@source` (the silent-failure rule from R6 — verify by build + probe)
- Modify: root `package.json` to add `dev:rag` and the rag dev shell importer
- Modify: root `Makefile` if needed (it already iterates over all `dev` shells via pnpm filters)

- [ ] **Step 1: Create `package.json`**

Source-only:
```json
{
  "name": "cliver-playbook-app-rag",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts",
    "./*": "./src/*"
  },
  "dependencies": {
    "cliver-playbook-app-basic": "workspace:*",
    "cliver-playbook-app-user": "workspace:*",
    "lucide-react": "^0.550.0",
    "react-i18next": "*",
    "react-router-dom": "*",
    "sonner": "*"
  },
  "devDependencies": { ... (same shape as app-mcp) }
}
```

- [ ] **Step 2: Create the barrel `src/index.ts`**

Re-exports `ragRoutes`, `ragNavItems`, `ragTranslations`, plus the api helpers.

- [ ] **Step 3: Create `src/routes.tsx`**

```ts
export const ragRoutes: RouteObject[] = [
  { path: "rag/documents", element: <RagDocumentsPage /> },
  { path: "rag/chat", element: <RagChatPage /> },
];
export const ragStandaloneRoutes: RouteObject[] = [];
export const ragAdminRoutes: RouteObject[] = [
  { path: "admin/rag", element: <RequirePerm code="rag:admin:read"><RagAdminPage /></RequirePerm> },
];
```

- [ ] **Step 4: Create `src/nav.ts`**

```ts
import type { AuthedNavItem } from "cliver-playbook-app-user/layout/AuthAppLayout.tsx";
export const ragNavItems: AuthedNavItem[] = [
  { to: "/rag/documents", labelKey: "nav.ragDocuments", perm: "rag:documents:read" },
  { to: "/rag/chat", labelKey: "nav.ragChat", perm: "rag:chat:read" },
];
```

- [ ] **Step 5: Create the locales**

~30 keys split into `nav.rag{Chat,Documents,Admin}`, `rag.documents.{title,upload,chunkCount,...}`, `rag.chat.{title,question,answer,citations,noHits,...}`, `rag.common.{chunker,embedder,recursive,markdown,code,pdf,bgeM3,stub,...}`. en + zh key-identical.

- [ ] **Step 6: Create the API wrappers**

`src/api/rag.ts` exports typed functions calling `/api/v1/rag/{documents,search,chat}` using the basic axios client.

- [ ] **Step 7: Create the pages**

**RagDocumentsPage**:
- A `StageSelector` with two dropdowns (`chunker`, `embedder`) and advanced settings (`chunk_size`, `chunk_overlap`) collapsed.
- A file input.
- A "Preview" button that uploads and shows the returned chunk list (via `ChunkPreview`).
- A "Index" button that POSTs to `/index`.
- Below: a list of indexed documents with status, chunker_id, embedder_id, chunk_count.

**RagChatPage**:
- A textarea for the question.
- A "Ask" button.
- Below: the answer (rendered Markdown-safe) and the citations (`CitationBadge` per chunk).
- An "I could not find anything relevant" empty state when `no_hits=true`.

**RagAdminPage**: paginated table of all documents across all users.

- [ ] **Step 8: Add the dev shell**

`dev/package.json`, `dev/src/main.tsx`, `dev/src/App.tsx`, `dev/src/index.css` (with the silent-failure rule), `dev/index.html`, `dev/tsconfig*.json`, `dev/.oxlintrc.json`, `dev/vite.config.ts` (proxy `/api` and `/mcp` like mcp shell does).

- [ ] **Step 9: Wire into mcp dev shell**

`mcp/dev/src/App.tsx` adds the rag routes:
```tsx
const routes: RouteObject[] = [
  { element: <AuthAppLayout extraNavItems={ragNavItems} />,
    children: [...basicRoutes, ...userRoutes, ...mcpRoutes, ...ragRoutes] },
  ...userStandaloneRoutes, ...ragStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];
```

`mcp/dev/src/main.tsx` adds rag translations:
```ts
installAuthClient();
createI18n(userTranslations, mcpTranslations, ragTranslations);
```

`mcp/dev/src/index.css` adds the rag `@source` (the R6 silent-failure rule):
```css
@import "cliver-playbook-app-basic/styles/index.css";
@source "../../src";
@source "../../../cliver-playbook-app-user/src";
@source "../../../cliver-playbook-app-rag/src";
```

`mcp/dev/vite.config.ts` does NOT need a new proxy — the RAG endpoints live under `/api/v1/rag/*`, which is already proxied.

- [ ] **Step 10: Update root `package.json` and `pnpm install`**

- [ ] **Step 11: Run the frontend gate**

```bash
pnpm -r typecheck
pnpm -r lint
pnpm -r build
```

Expected: PASS. The mcp shell's CSS probe should include one rag-only utility (e.g. a class name unique to the rag pages) — verify by grep.

- [ ] **Step 12: Live end-to-end**

1. `make db-up` + `make db-init` + `make backend-start` + `pnpm --filter cliver-playbook-dev-mcp dev`.
2. Open `http://127.0.0.1:5173/rag/documents` in a browser.
3. Pick `Markdown` chunker + `BGE-M3` embedder, upload a small Markdown file, click "Preview" → see chunks.
4. Click "Index" → see "indexed" status.
5. Open `http://127.0.0.1:5173/rag/chat`, type a question that should match, click "Ask" → see the stub answer with citations.
6. Open `http://127.0.0.1:5173/admin/rag` (as admin) → see the document in the list.

- [ ] **Step 13: Commit**

```bash
git add packages/frontend/cliver-playbook-app-rag/ \
        packages/frontend/cliver-playbook-app-mcp/ \
        package.json pnpm-lock.yaml
git commit -m "feat(rag frontend): source-only package, 2 pages, dev shell, mcp shell composition"
```

---

### Task 14: `make check` green + README + final commit

**Files:**
- Modify: `README.md` (add the RAG package to the tables + a short section)
- Modify: `.env.example` (add a `rag:` block — retriever / embedder / reranker selection knobs)
- Possibly modify: `app.yaml` (add a `rag:` block with the offline defaults)

- [ ] **Step 1: Run the full `make check` gate**

```bash
cd /Users/lgao/sources/cliver-project/mcp_x/cliver-playbook
make check
```

Expected: PASS.
- ruff ×4 packages (basic / user / mcp / rag) green.
- pytest: basic 16 + user 76 + mcp 58 + rag ~25 = ~175 tests.
- frontend: typecheck / lint / build ×7 projects (3 packages + 3 dev shells + new rag dev shell) green.

- [ ] **Step 2: Add the RAG section to the README**

Two sentences in the "Packages" tables + a "Knowledge base / RAG" section that shows the per-stage flow with a screenshot placeholder and a code snippet of `import { ragRoutes, ragNavItems, ragTranslations } from "cliver-playbook-app-rag"`.

- [ ] **Step 3: Add the rag block to `.env.example`**

A `rag:` block with the offline defaults and a comment block explaining what an operator flips for production.

- [ ] **Step 4: Final live smoke (end-to-end)**

Re-run the Task 13.12 end-to-end with the composed stack:
1. Upload a Markdown doc with `markdown` chunker + `stub` embedder (instant).
2. Click "Index" — see it in the list.
3. Open chat, ask a matching question, see the answer.
4. Re-upload the same file — confirm idempotent (same document id, no duplicate rows).

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example app.yaml
git commit -m "docs: RAG module in README, .env.example, app.yaml"
```

---

## Self-Review

1. **Spec coverage** — every section of the design doc maps to a task. Intent + why → Task 1 architecture choice. Goals → Tasks 6/7 (upload + per-stage selection) + 11 (chat). Non-goals → not addressed (correctly skipped). Anti-goals → enforced by Tasks 2 (no ALTER, no mcp_tokens), 3 (audit JSONB), 6 (no Mount). Constraints → Tasks 1/13 (package shape), 1 (workspace). Architecture overview → Tasks 4–11. Default tools → Tasks 4/5/8/10/11. How it lands → Tasks 12/13. Why this design → captured in the ADR (Task 12.6) and the spec.

2. **Step scan** — every step is one action with a checkable result. No step says "TBD" or "handle edge cases" without specifying which edge case. No step's body overwrites the implementer; every code block is either the exact test (so the implementer can paste it) or the exact signature (so the implementer writes the body). The PDF test mocks the partition call so the test doesn't need a real PDF; the BGE-M3 test only checks metadata; the BGE-reranker test only checks the model_id — keeping unit tests offline-friendly.

3. **Type consistency** — the `Chunker.split`, `Embedder.embed`, `Retriever.retrieve`, `Reranker.rerank`, `LLM.generate` method signatures are identical across their first appearance (Task 4/5/8/10/11) and their use sites (Tasks 6/8/9/11). The `Hit` and `Query` types are defined in Task 8 and reused in Task 10/11. The `Document` and `Chunk` types are defined in Task 4 and used in Task 6.

4. **Review Focus** — five failure modes named in the plan header, each with its test pin: empty file (Task 6), re-indexing (Task 7), empty index (Task 9), image-only PDF (Task 6), no-hits query (Task 11). An empty RAG database and an unreachable embedder are silent in the protocol shapes; a test that exercises the no-embedder path would require an out-of-process test scaffold (out of scope for v1; documented as a follow-up).

5. **Proportion** — the plan is 14 tasks; the spec is one document of ~250 lines. The plan is roughly the same scale, with each task's body being a file path + a method signature + a 5–15 line test. The longest single block is the per-stage Task 6 (upload + index), which is the most behaviourally rich endpoint and warrants the detail. No step dictates a function body that the test does not already determine.
