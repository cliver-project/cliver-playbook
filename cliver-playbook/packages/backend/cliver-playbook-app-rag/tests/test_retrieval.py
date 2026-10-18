"""Retriever registry, RRF fusion, and the offline BM25 implementation.

The pgvector-hybrid retriever's SQL is PostgreSQL-specific and is
exercised by the live smoke run; these tests pin everything that does
not need a server: the registry contract, the pure fusion function, and
the bm25-only fallback over the shared ORM (SQLite).
"""

from __future__ import annotations

import pytest

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.rag.models.entities import Chunk, Document
from cliver_playbook.app.rag.retrieval import Hit, Query, get_retriever, registry
from cliver_playbook.app.rag.retrieval.bm25_only import Bm25OnlyRetriever
from cliver_playbook.app.rag.retrieval.pgvector_hybrid import rrf_fuse


def _hit(chunk_id: str, score: float = 0.0) -> Hit:
    return Hit(
        chunk_id=chunk_id,
        document_id="doc",
        ordinal=0,
        text=f"text-{chunk_id}",
        score=score,
    )


def test_registry_lists_both_shipped_retrievers() -> None:
    assert {"bm25-only", "pgvector-hybrid"} <= registry.names()


def test_unknown_retriever_raises() -> None:
    with pytest.raises(KeyError, match="unknown retriever"):
        get_retriever("does-not-exist")


def test_registry_returns_fresh_instances() -> None:
    first = get_retriever("bm25-only")
    second = get_retriever("bm25-only")
    assert isinstance(first, Bm25OnlyRetriever)
    assert first is not second


def test_rrf_fusion_prefers_chunks_found_by_both_legs() -> None:
    dense = [_hit("a"), _hit("b")]
    sparse = [_hit("b"), _hit("c")]

    fused = rrf_fuse(dense, sparse, top_k=3)

    # b is rank 2 dense + rank 1 sparse: 1/62 + 1/61, outranking a
    # (1/61) and c (1/62). Scores are RRF sums, not leg scores.
    assert [hit.chunk_id for hit in fused] == ["b", "a", "c"]
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_fusion_respects_top_k() -> None:
    fused = rrf_fuse([_hit("a"), _hit("b")], [_hit("c")], top_k=1)
    assert len(fused) == 1


async def _seed_two_chunks() -> None:
    factory = runtime.session_factory()
    async with factory() as db:
        db.add(
            Document(
                id="d1",
                title="Doc",
                source_uri="doc.txt",
                mime_type="text/plain",
                chunker_id="recursive",
                embedder_id="stub",
                dim=64,
            )
        )
        db.add_all(
            [
                Chunk(
                    id="c1",
                    document_id="d1",
                    ordinal=0,
                    text="the quick brown fox jumps over the lazy dog",
                    token_count=9,
                ),
                Chunk(
                    id="c2",
                    document_id="d1",
                    ordinal=1,
                    text="lorem ipsum dolor sit amet consectetur",
                    token_count=6,
                ),
            ]
        )
        await db.commit()


async def test_bm25_only_returns_only_matching_chunks(app) -> None:
    await _seed_two_chunks()
    factory = runtime.session_factory()
    async with factory() as db:
        hits = await Bm25OnlyRetriever().retrieve(Query(text="quick fox", top_k=5), db=db)

    assert [hit.chunk_id for hit in hits] == ["c1"]
    assert hits[0].document_id == "d1"
    assert hits[0].ordinal == 0
    assert hits[0].score > 0


async def test_bm25_only_respects_top_k(app) -> None:
    await _seed_two_chunks()
    factory = runtime.session_factory()
    async with factory() as db:
        hits = await Bm25OnlyRetriever().retrieve(Query(text="quick lorem", top_k=1), db=db)

    assert len(hits) == 1


async def test_bm25_only_empty_index_returns_empty(app) -> None:
    factory = runtime.session_factory()
    async with factory() as db:
        hits = await Bm25OnlyRetriever().retrieve(Query(text="anything", top_k=5), db=db)
    assert hits == []


async def test_bm25_only_blank_query_returns_empty(app) -> None:
    await _seed_two_chunks()
    factory = runtime.session_factory()
    async with factory() as db:
        hits = await Bm25OnlyRetriever().retrieve(Query(text="   ", top_k=5), db=db)
    assert hits == []
