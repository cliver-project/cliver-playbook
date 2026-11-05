"""Production retriever: pgvector cosine + Postgres full-text, RRF-fused.

Two legs, two engines:

- **Dense** — cosine similarity over ``rag_chunk_embeddings``. The
  query is embedded with the per-call embedder override when the request
  carries one, otherwise with the embedder named by
  ``settings.rag.embedder``. Rows are filtered by the embedder's
  identity as well as its dimension: vectors from different models live
  in different spaces even at the same width, so a mixed corpus must
  only compare comparable rows. When the query dimension is 1024 (the
  production default), the SQL uses the same expression the partial
  HNSW index is built on, so the index is actually eligible; other
  dimensions fall back to a sequential scan, which is fine at
  development scale and is the price of a mixed-dim column. The query
  embedding runs in a worker thread — model inference must not block
  the event loop.
- **Sparse** — Postgres ``to_tsvector`` / ``plainto_tsquery`` with
  ``ts_rank_cd``. The lexical representation is ``search_text`` when
  the governance pipeline produced one (a contextual prefix plus the
  child text), else the original chunk text. No stored tsvector column
  yet: the expression is computed per query. A future migration can add
  a generated column and a GIN index without changing this interface.

Both legs join ``rag_documents`` and keep only ``status = 'indexed'``
rows. Upload stores chunks before embedding (for the preview), and a
failed document may retain rows, so the status predicate is what keeps
the "nothing is searchable until you index" contract true.

The access predicate, the structured filter and the distance expression
are all SQLAlchemy expressions with bound parameters, applied to BOTH
legs. The distance casts the stored vector to the query's dimension so
the partial HNSW index stays eligible, and the query vector travels as
a typed bind so the driver never sees interpolated SQL. The only raw
SQL is the ``set_config`` call that widens ``hnsw.ef_search`` for the
current transaction; its value is bound, not formatted.

Fusion is reciprocal rank fusion (k=60). Scores on each leg live on
different scales (cosine similarity vs ``ts_rank_cd``), so fusing ranks
instead of raw scores is what makes hybrid retrieval stable. The fused
``score`` is the RRF sum; it is deliberately small and is not
comparable to either leg's raw score — rerankers and floors apply to
their own scales.

This retriever is Postgres-only. SQLite test runs select ``bm25-only``
through settings; the two implementations share the seam, not the SQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, bindparam, cast, func, literal, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import policy_for
from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.filters import compile_filter
from cliver_playbook.app.rag.models.entities import Chunk, ChunkEmbedding, ChunkParent, Document
from cliver_playbook.app.rag.retrieval.base import Hit, Query
from cliver_playbook.app.rag.settings import settings

logger = logging.getLogger("cliver_playbook.app.rag.retrieval.pgvector_hybrid")

# Reciprocal-rank-fusion constant from the original RRF paper; the
# value damps top-rank dominance and is the community default.
_RRF_K = 60

# The dimension the partial HNSW index covers (the BGE-M3 default).
_INDEXED_DIM = 1024


def _as_metadata(value: Any) -> dict[str, Any]:
    """Normalize a JSONB column value from a raw/compiled query.

    The ORM result processor parses JSONB, but a raw SQL statement goes
    straight to the driver: asyncpg returns ``jsonb`` as a string. A
    driver that returns a dict already passes through unchanged.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def _row_to_hit(row: Any) -> Hit:
    return Hit(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        ordinal=row["ordinal"],
        text=row["text"],
        score=float(row["score"]),
        metadata=_as_metadata(row["metadata"]),
        parent_id=row["parent_id"],
        parent_text=row["parent_text"],
        document_metadata=_as_metadata(row["document_metadata"]),
        logical_id=row["logical_id"],
        classification=row["classification"],
    )


def _hit_columns() -> tuple[Any, ...]:
    """The columns both legs return, so fusion sees equivalent Hits."""
    return (
        Chunk.id.label("chunk_id"),
        Chunk.document_id,
        Chunk.ordinal,
        Chunk.text,
        Chunk.metadata_json.label("metadata"),
        Chunk.parent_id,
        ChunkParent.text.label("parent_text"),
        Document.logical_id,
        Document.classification,
        Document.metadata_json.label("document_metadata"),
    )


def _base_clauses(query: Query) -> list[Any]:
    """Status + access + structured filter, applied to both legs."""
    clauses: list[Any] = [
        Document.status == "indexed",
        policy_for(query.access).predicate(query.access),
    ]
    structured = compile_filter(query.filters)
    if structured is not None:
        clauses.append(structured)
    return clauses


def rrf_fuse(
    dense: list[Hit],
    sparse: list[Hit],
    *,
    top_k: int,
    k: int = _RRF_K,
) -> list[Hit]:
    """Fuse two ranked lists with reciprocal rank fusion.

    Each hit contributes ``1 / (k + rank)`` per list it appears in, with
    rank starting at 1. A chunk found by both legs outranks one found by
    either alone. Ties keep first-seen order (dense leg inserted first)
    because Python's sort is stable.
    """
    fused_scores: dict[str, float] = {}
    by_id: dict[str, Hit] = {}
    for ranked in (dense, sparse):
        for rank, hit in enumerate(ranked, start=1):
            fused_scores[hit.chunk_id] = fused_scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            by_id.setdefault(hit.chunk_id, hit)
    fused = [
        hit.model_copy(update={"score": fused_scores[chunk_id]}) for chunk_id, hit in by_id.items()
    ]
    fused.sort(key=lambda hit: hit.score, reverse=True)
    return fused[:top_k]


class PgvectorHybridRetriever:
    """Dense + sparse retrieval over Postgres, fused with RRF."""

    name = "pgvector-hybrid"
    modes = frozenset({"dense", "sparse", "hybrid"})

    def effective_mode(self, mode: str) -> str:
        return mode

    async def retrieve(self, query: Query, *, db: AsyncSession) -> list[Hit]:
        if not query.text.strip() or query.top_k <= 0:
            return []
        # Each leg over-fetches, then fusion trims to top_k. Ranking
        # fusion can only reorder the candidates it is given, so a
        # shared candidate pool must be wider than the final result.
        candidates = max(query.top_k * 2, 20)

        dense: list[Hit] = []
        if query.mode in ("dense", "hybrid"):
            dense = await self._dense(query, candidates, db)
        sparse: list[Hit] = []
        if query.mode in ("sparse", "hybrid"):
            sparse = await self._sparse(query, candidates, db)

        if query.mode == "dense":
            return dense[: query.top_k]
        if query.mode == "sparse":
            return sparse[: query.top_k]
        return rrf_fuse(dense, sparse, top_k=query.top_k)

    async def _dense(self, query: Query, limit: int, db: AsyncSession) -> list[Hit]:
        """Cosine-similarity leg. An empty embedding table skips the
        embedder entirely, so an empty index never pays a model load.
        """
        query_text = query.text
        stored = await db.scalar(sql_text("SELECT count(*) FROM rag_chunk_embeddings"))
        if not stored:
            return []

        embedder = get_embedder(query.embedder or settings.rag.embedder)
        vectors = await asyncio.to_thread(embedder.embed, [query_text], mode="query")
        vector = vectors[0]
        dim = len(vector)

        # The partial HNSW index is built on (embedding::vector(1024))
        # WHERE dim = 1024, so the query must cast to the same type for
        # the planner to consider it. The cast and the dim predicate
        # below are the documented pgvector pattern for a
        # mixed-dimension column; other dimensions fall back to a
        # sequential scan.
        cast_type = Vector(dim)
        if dim == _INDEXED_DIM:
            # HNSW recalls at most ef_search rows, so the breadth must be
            # at least the LIMIT or a large top_k silently truncates.
            # `SET` cannot take a bind parameter; set_config(..., true)
            # scopes the change to the current transaction. The setting
            # only matters when the index is eligible, i.e. this branch.
            ef_search = max(settings.rag.pgvector_ef_search, limit)
            await db.execute(
                sql_text("SELECT set_config('hnsw.ef_search', :ef, true)"),
                {"ef": str(ef_search)},
            )

        # A typed expression (rather than raw SQL) keeps the bind typed:
        # pgvector's bind processor formats the Python list as a vector
        # literal. ``literal`` carries an explicit Float type because the
        # distance expression itself is Vector-typed, and the implicit
        # coercion would otherwise try to bind the 1 through pgvector.
        distance = cast(ChunkEmbedding.embedding, cast_type).op("<=>")(
            bindparam("qvec", value=vector, type_=cast_type)
        )
        score = (literal(1.0, Float) - distance).label("score")
        statement = (
            select(*_hit_columns(), score)
            .select_from(Chunk)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .join(Document, Document.id == Chunk.document_id)
            .outerjoin(ChunkParent, ChunkParent.id == Chunk.parent_id)
            .where(
                *_base_clauses(query),
                ChunkEmbedding.dim == dim,
                ChunkEmbedding.embedder_version == embedder.id,
            )
            # Ascending distance is descending similarity, and it is the
            # bare expression the HNSW index is ordered by. Ordering on
            # the transformed score would make the index ineligible.
            .order_by(distance)
            .limit(limit)
        )
        rows = (await db.execute(statement)).mappings().all()
        return [_row_to_hit(row) for row in rows]

    async def _sparse(self, query: Query, limit: int, db: AsyncSession) -> list[Hit]:
        """Full-text leg, ranked by Postgres cover density.

        ``search_text`` is the contextual retrieval representation; a
        legacy chunk without one falls back to its original text.
        """
        tsv = func.to_tsvector("english", func.coalesce(Chunk.search_text, Chunk.text))
        tsquery = func.plainto_tsquery("english", bindparam("q"))
        score = func.ts_rank_cd(tsv, tsquery).label("score")
        statement = (
            select(*_hit_columns(), score)
            .select_from(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .outerjoin(ChunkParent, ChunkParent.id == Chunk.parent_id)
            .where(*_base_clauses(query), tsv.op("@@")(tsquery))
            .order_by(score.desc())
            .limit(limit)
        )
        rows = (await db.execute(statement, {"q": query.text})).mappings().all()
        return [_row_to_hit(row) for row in rows]
