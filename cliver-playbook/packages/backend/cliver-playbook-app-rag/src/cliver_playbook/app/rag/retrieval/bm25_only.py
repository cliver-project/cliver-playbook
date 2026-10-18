"""Offline retriever: rank the chunk table with BM25 in Python.

Why not an in-memory index populated by upserts: the chunk table is the
single source of truth, and an index that only learns about chunks
through a second write path drifts the moment anything else writes a
row. Reading the chunks per query is O(corpus) and intentionally
simple — it exists so a developer (or a test run on SQLite) can answer
queries with no pgvector, and it is not the production default.

Tokenization is a lower-cased ASCII word scan. That is honest about its
limits: it works for English-like text, and a CJK corpus should use the
Postgres full-text leg (which has its own configuration) rather than
this fallback.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25L
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Chunk
from cliver_playbook.app.rag.retrieval.base import Hit, Query

_WORD = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lower-cased word tokens; punctuation and whitespace separate."""
    return _WORD.findall(text.lower())


class Bm25OnlyRetriever:
    """Lexical-only retrieval computed over the chunk table."""

    name = "bm25-only"

    async def retrieve(self, query: Query, *, db: AsyncSession) -> list[Hit]:
        query_tokens = _tokenize(query.text)
        if not query_tokens:
            return []

        rows = (await db.execute(select(Chunk).order_by(Chunk.ordinal))).scalars().all()
        if not rows:
            return []

        # BM25L rather than BM25Okapi: Okapi's IDF is log((N-n+0.5)/
        # (n+0.5)), which is exactly zero when a term appears in half a
        # tiny corpus and negative beyond that — so on a few-chunk
        # development index the "obvious" match would score 0. BM25L's
        # log(N+1) - log(n+0.5) stays positive, and its score term is
        # proportional to term frequency, so a chunk with no query term
        # still scores exactly 0 (unlike BM25Plus, whose delta gives
        # every document a positive score for every query term).
        # An empty document set would make the scorer divide by zero;
        # the guard above covers it. Chunks whose text has no tokens
        # still need an entry, otherwise scores misalign with rows.
        corpus = [_tokenize(row.text) for row in rows]
        bm25 = BM25L(corpus)
        scores = bm25.get_scores(query_tokens)

        ranked = sorted(zip(rows, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        hits: list[Hit] = []
        for row, score in ranked:
            if score <= 0:
                # Non-matching documents score exactly zero; a
                # zero-scored row is noise, not a low-confidence hit.
                break
            hits.append(
                Hit(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    ordinal=row.ordinal,
                    text=row.text,
                    score=float(score),
                    metadata=row.metadata_json or {},
                )
            )
            if len(hits) >= query.top_k:
                break
        return hits
