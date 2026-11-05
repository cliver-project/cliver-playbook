"""Live pgvector retrieval checks, opt-in through a dedicated database.

SQLite cannot run the production dense/sparse SQL, so the unit suite
only covers BM25 and the predicate compilation. This module runs the
real legs when ``GOV_TEST_DATABASE_URL`` points at a disposable
Postgres+pgvector database (the repository's isolated test container):

    docker run --rm -d --name cliver_gov_test_db \
      -p 127.0.0.1:15432:5432 \
      -e POSTGRES_USER=cliver -e POSTGRES_PASSWORD=cliver -e POSTGRES_DB=cliver_app \
      pgvector/pgvector:pg16
    export GOV_TEST_DATABASE_URL=postgresql+psycopg://cliver:cliver@127.0.0.1:15432/cliver_app

Without the variable the module skips, so CI does not need Docker.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cliver_playbook.app.rag.access import AccessScope
from cliver_playbook.app.rag.embedding.stub import StubEmbedder
from cliver_playbook.app.rag.models.base import Base
from cliver_playbook.app.rag.models.entities import (
    Chunk,
    ChunkEmbedding,
    ChunkParent,
    Document,
)
from cliver_playbook.app.rag.retrieval import Query
from cliver_playbook.app.rag.retrieval.pgvector_hybrid import PgvectorHybridRetriever

DATABASE_URL = os.getenv("GOV_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="GOV_TEST_DATABASE_URL is not set")


@pytest.fixture()
async def factory():
    sync_engine = create_engine(DATABASE_URL)
    with sync_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(sync_engine, checkfirst=True)
    with sync_engine.begin() as conn:
        conn.execute(text("DELETE FROM rag_chunk_embeddings"))
        conn.execute(text("DELETE FROM rag_chunks"))
        conn.execute(text("DELETE FROM rag_chunk_parents"))
        conn.execute(text("DELETE FROM rag_documents"))

    async_engine = create_async_engine(DATABASE_URL.replace("+psycopg", "+asyncpg"))
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    yield session_factory
    await async_engine.dispose()
    sync_engine.dispose()


async def _seed(factory) -> None:
    embedder = StubEmbedder()
    vectors = embedder.embed(["revenue figures", "revenue figures"])
    async with factory() as db:
        db.add_all(
            [
                Document(
                    id="pg-low",
                    title="Low",
                    mime_type="text/markdown",
                    chunker_id="parent-child",
                    embedder_id="stub",
                    dim=64,
                    status="indexed",
                    published=True,
                    classification=1,
                    collection_id="finance",
                    logical_id="low-doc",
                    metadata_json={"doc_type": "policy"},
                ),
                Document(
                    id="pg-high",
                    title="High",
                    mime_type="text/markdown",
                    chunker_id="parent-child",
                    embedder_id="stub",
                    dim=64,
                    status="indexed",
                    published=True,
                    classification=3,
                    collection_id="finance",
                    logical_id="high-doc",
                    metadata_json={"doc_type": "report"},
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                ChunkParent(id="pg-p-low", document_id="pg-low", ordinal=0, text="parent low"),
                ChunkParent(id="pg-p-high", document_id="pg-high", ordinal=0, text="parent high"),
            ]
        )
        await db.flush()
        db.add_all(
            [
                Chunk(
                    id="pg-c-low",
                    document_id="pg-low",
                    ordinal=0,
                    text="original child",
                    search_text="revenue figures",
                    token_count=2,
                    parent_id="pg-p-low",
                ),
                Chunk(
                    id="pg-c-high",
                    document_id="pg-high",
                    ordinal=0,
                    text="original child",
                    search_text="revenue figures",
                    token_count=2,
                    parent_id="pg-p-high",
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                ChunkEmbedding(
                    chunk_id="pg-c-low",
                    embedding=vectors[0],
                    dim=64,
                    embedder_version="stub@1.0",
                ),
                ChunkEmbedding(
                    chunk_id="pg-c-high",
                    embedding=vectors[1],
                    dim=64,
                    embedder_version="stub@1.0",
                ),
            ]
        )
        await db.commit()


async def test_dense_leg_applies_access_and_returns_the_parent(factory) -> None:
    await _seed(factory)
    async with factory() as db:
        hits = await PgvectorHybridRetriever().retrieve(
            Query(
                text="revenue figures",
                top_k=5,
                mode="dense",
                embedder="stub",
                access=AccessScope(collection_id="finance", governed=True, clearance=1),
            ),
            db=db,
        )
    assert [hit.chunk_id for hit in hits] == ["pg-c-low"]
    assert hits[0].parent_text == "parent low"
    assert hits[0].logical_id == "low-doc"
    assert hits[0].document_metadata["doc_type"] == "policy"


async def test_hybrid_legs_agree_and_the_grant_restores_the_high_doc(factory) -> None:
    await _seed(factory)
    async with factory() as db:
        hits = await PgvectorHybridRetriever().retrieve(
            Query(
                text="revenue figures",
                top_k=5,
                mode="hybrid",
                embedder="stub",
                access=AccessScope(
                    collection_id="finance",
                    governed=True,
                    clearance=1,
                    grants=frozenset({"high-doc"}),
                ),
            ),
            db=db,
        )
    assert {hit.chunk_id for hit in hits} == {"pg-c-low", "pg-c-high"}


async def test_sparse_leg_uses_the_contextual_representation(factory) -> None:
    await _seed(factory)
    async with factory() as db:
        hits = await PgvectorHybridRetriever().retrieve(
            Query(
                text="contextual",
                top_k=5,
                mode="sparse",
                access=AccessScope(collection_id="finance", governed=True, clearance=3),
            ),
            db=db,
        )
    # "contextual" is not in either original child; it only exists in a
    # search_text this test rewrites below.
    assert hits == []

    async with factory() as db:
        chunk = await db.get(Chunk, "pg-c-low")
        chunk.search_text = "contextual revenue figures"
        await db.commit()
        hits = await PgvectorHybridRetriever().retrieve(
            Query(
                text="contextual",
                top_k=5,
                mode="sparse",
                access=AccessScope(collection_id="finance", governed=True, clearance=1),
            ),
            db=db,
        )
    assert [hit.chunk_id for hit in hits] == ["pg-c-low"]
