"""Production retriever: pgvector cosine + Postgres full-text, RRF-fused.

Two legs, two engines:

- **Dense** — cosine similarity over ``rag_chunk_embeddings``. The
  query is embedded with the per-call embedder override when the request
  carries one, otherwise with the embedder named by
  ``settings.rag.embedder``, and matched only against rows of the same
  dimension, because the knowledge base may hold vectors from more than
  one embedder. When the
  query dimension is 1024 (the production default), the SQL uses the
  same expression the partial HNSW index is built on, so the index is
  actually eligible; other dimensions fall back to a sequential scan,
  which is fine at development scale and is the price of a mixed-dim
  column. The query embedding runs in a worker thread — model
  inference must not block the event loop.
- **Sparse** — Postgres ``to_tsvector`` / ``plainto_tsquery`` with
  ``ts_rank_cd``. No stored tsvector column yet: the expression is
  computed per query. A future migration can add a generated column and
  a GIN index without changing this interface.

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

from pgvector import Vector as PgVector
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.retrieval.base import Hit, Query
from cliver_playbook.app.rag.settings import settings

logger = logging.getLogger("cliver_playbook.app.rag.retrieval.pgvector_hybrid")

# Reciprocal-rank-fusion constant from the original RRF paper; the
# value damps top-rank dominance and is the community default.
_RRF_K = 60

# The dimension the partial HNSW index covers (the BGE-M3 default).
_INDEXED_DIM = 1024


def _as_metadata(value: Any) -> dict[str, Any]:
    """Normalize a JSONB column value from a raw ``text()`` query.

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
    )


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

    async def retrieve(self, query: Query, *, db: AsyncSession) -> list[Hit]:
        if not query.text.strip() or query.top_k <= 0:
            return []
        # Each leg over-fetches, then fusion trims to top_k. Ranking
        # fusion can only reorder the candidates it is given, so a
        # shared candidate pool must be wider than the final result.
        candidates = max(query.top_k * 2, 20)

        dense: list[Hit] = []
        if query.mode in ("dense", "hybrid"):
            dense = await self._dense(query.text, candidates, db, query.embedder)
        sparse: list[Hit] = []
        if query.mode in ("sparse", "hybrid"):
            sparse = await self._sparse(query.text, candidates, db)

        if query.mode == "dense":
            return dense[: query.top_k]
        if query.mode == "sparse":
            return sparse[: query.top_k]
        return rrf_fuse(dense, sparse, top_k=query.top_k)

    async def _dense(
        self,
        query_text: str,
        limit: int,
        db: AsyncSession,
        embedder_name: str | None = None,
    ) -> list[Hit]:
        """Cosine-similarity leg. An empty embedding table skips the
        embedder entirely, so an empty index never pays a model load.

        ``embedder_name`` is the per-call override carried by the query;
        without it the configured default embeds the query. The vectors
        and the query must come from the same model, so callers that
        indexed with a non-default embedder must pass its name here.
        """
        stored = await db.scalar(sql_text("SELECT count(*) FROM rag_chunk_embeddings"))
        if not stored:
            return []

        embedder = get_embedder(embedder_name or settings.rag.embedder)
        vectors = await asyncio.to_thread(embedder.embed, [query_text], mode="query")
        vector = vectors[0]
        dim = len(vector)
        query_vector = PgVector(vector).to_text()

        # The partial HNSW index is built on (embedding::vector(1024))
        # WHERE dim = 1024, so the query must spell the expression and
        # the predicate exactly for the planner to consider it.
        if dim == _INDEXED_DIM:
            # HNSW recall is tuned per transaction. `SET` cannot take a
            # bind parameter; set_config(..., true) scopes the change to
            # the current transaction. The setting only matters when the
            # index is eligible, i.e. in this branch.
            await db.execute(
                sql_text("SELECT set_config('hnsw.ef_search', :ef, true)"),
                {"ef": str(settings.rag.pgvector_ef_search)},
            )
            distance = "(e.embedding::vector(1024)) <=> CAST(:qvec AS vector(1024))"
            where = "e.dim = 1024"
            params: dict[str, Any] = {"qvec": query_vector, "limit": limit}
        else:
            distance = "e.embedding <=> CAST(:qvec AS vector)"
            where = "e.dim = :dim"
            params = {"qvec": query_vector, "dim": dim, "limit": limit}

        statement = sql_text(
            "SELECT e.chunk_id, c.document_id, c.ordinal, c.text, c.metadata, "
            f"1 - ({distance}) AS score "
            "FROM rag_chunk_embeddings AS e "
            "JOIN rag_chunks AS c ON c.id = e.chunk_id "
            f"WHERE {where} "
            f"ORDER BY {distance} "
            "LIMIT :limit"
        )
        rows = (await db.execute(statement, params)).mappings().all()
        return [_row_to_hit(row) for row in rows]

    async def _sparse(self, query_text: str, limit: int, db: AsyncSession) -> list[Hit]:
        """Full-text leg, ranked by Postgres cover density."""
        statement = sql_text(
            "SELECT c.id AS chunk_id, c.document_id, c.ordinal, c.text, c.metadata, "
            "ts_rank_cd(to_tsvector('english', c.text), "
            "plainto_tsquery('english', :q)) AS score "
            "FROM rag_chunks AS c "
            "WHERE to_tsvector('english', c.text) @@ plainto_tsquery('english', :q) "
            "ORDER BY score DESC "
            "LIMIT :limit"
        )
        rows = (await db.execute(statement, {"q": query_text, "limit": limit})).mappings().all()
        return [_row_to_hit(row) for row in rows]
