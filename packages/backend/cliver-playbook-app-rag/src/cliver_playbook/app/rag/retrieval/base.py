"""Retriever protocol + the Query / Hit wire shapes.

The retriever is the third of the five RAG stages. It is a READ seam:
ingestion writes chunks and embeddings directly (the upload / index
endpoints own that transaction), so the protocol deliberately has no
``upsert`` / ``delete`` — a second write API would be dead surface that
could drift from the table it claims to maintain.

``retrieve`` takes the request-scoped ``AsyncSession`` explicitly
rather than opening its own: the caller owns the transaction boundary,
and a retriever never commits. The bm25-only implementation ignores
the session's engine specifics (it queries the chunk table through the
ORM), so the same seam works on SQLite tests and Postgres production.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope
from cliver_playbook.app.rag.filters import FilterNode


class Hit(BaseModel):
    """One retrieved chunk, ranked within its result list.

    ``text`` is the original child text. ``parent_text`` is the original
    parent section the generator should receive (small-to-big); it is
    None for legacy chunkers that have no parent representation.
    ``metadata`` is chunk-level metadata, ``document_metadata`` is the
    document's JSONB metadata.
    """

    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    parent_text: str | None = None
    document_metadata: dict[str, Any] = Field(default_factory=dict)
    logical_id: str | None = None
    classification: int | None = None


class Query(BaseModel):
    """A retrieval request.

    ``mode`` selects which leg(s) run: dense (vector similarity), sparse
    (lexical / BM25 / tsquery), or hybrid (both, fused with reciprocal
    rank fusion). ``top_k`` is the final result count.

    ``embedder`` overrides the embedder used to embed the query text.
    It must name the embedder that produced the stored vectors: vectors
    from different embedders live in different spaces (and usually differ
    in dimension), so a query embedded by the wrong model can never
    match them. When omitted, the configured default is used.

    ``filters`` narrows the corpus by structured metadata.
    ``access`` is the caller's visibility predicate; it is mandatory in
    the sense that an omitted scope still applies the default
    (published, not deleted) rule.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str
    top_k: int = 20
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    embedder: str | None = None
    filters: FilterNode | None = None
    access: AccessScope = Field(default_factory=AccessScope)


class Retriever(Protocol):
    """The retriever seam.

    Implementations: ``PgvectorHybridRetriever`` (production default:
    pgvector cosine + Postgres full-text, RRF-fused) and
    ``Bm25OnlyRetriever`` (offline / test fallback that ranks the chunk
    table with rank_bm25 in Python). New retrievers register themselves
    at import via ``retrieval.registry.register(name, factory)``.
    """

    name: str
    # Retrieval modes this implementation can honour. A request for a
    # mode outside the set is a client error (422), not a silent
    # fallback: the UI compares modes, so it must know which leg ran.
    modes: frozenset[str]

    def effective_mode(self, mode: str) -> str:
        """The mode the implementation actually runs for ``mode``.

        Usually ``mode`` itself. A lexical-only retriever reports
        ``sparse`` for a ``hybrid`` request because no dense leg exists,
        which keeps the response and the audit row truthful.
        """
        ...

    async def retrieve(self, query: Query, *, db: AsyncSession) -> list[Hit]: ...
