"""Generic rag primitives the governance package builds on.

These columns and tables are deliberately part of the generic package:
a non-governance deployment pays for a handful of nullable columns, but
the retrieval and ingestion machinery stays in one place instead of
being duplicated in a governance fork. The table is created from ORM
metadata, so this also pins that the models stay in sync with the
migration.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from cliver_playbook.app.rag.models.base import Base
from cliver_playbook.app.rag.models.entities import Chunk, ChunkParent, Document


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


def test_document_carries_lineage_and_access_columns(engine) -> None:
    cols = {c["name"] for c in inspect(engine).get_columns("rag_documents")}
    assert {
        "logical_id",
        "classification",
        "collection_id",
        "metadata",
        "published",
        "pipeline_run_id",
        "source_updated_at",
        "content_hash",
        "deleted_at",
    }.issubset(cols)


def test_parent_table_and_chunk_link(engine) -> None:
    insp = inspect(engine)
    assert "rag_chunk_parents" in insp.get_table_names()
    fks = insp.get_foreign_keys("rag_chunks")
    assert any(fk["referred_table"] == "rag_chunk_parents" for fk in fks)
    assert "search_text" in {c["name"] for c in insp.get_columns("rag_chunks")}


def test_embedding_primary_key_is_composite(engine) -> None:
    pk = inspect(engine).get_pk_constraint("rag_chunk_embeddings")
    assert pk["constrained_columns"] == ["chunk_id", "embedder_version"]


def test_multiple_embedding_versions_can_coexist(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(
            Document(
                id="doc1",
                title="hello",
                mime_type="text/plain",
                chunker_id="recursive",
                embedder_id="stub",
                dim=4,
            )
        )
        s.flush()
        parent = ChunkParent(id="p1", document_id="doc1", ordinal=0, text="parent")
        s.add(parent)
        s.flush()
        chunk = Chunk(
            id="c1",
            document_id="doc1",
            ordinal=0,
            text="child",
            search_text="context\n\nchild",
            token_count=1,
            parent_id="p1",
        )
        s.add(chunk)
        s.flush()
        from cliver_playbook.app.rag.models.entities import ChunkEmbedding

        s.add_all(
            [
                ChunkEmbedding(
                    chunk_id="c1",
                    embedding=[0.0, 0.0, 0.0, 0.0],
                    dim=4,
                    embedder_version="stub@1.0",
                ),
                ChunkEmbedding(
                    chunk_id="c1",
                    embedding=[0.0, 0.0, 0.0, 0.0],
                    dim=4,
                    embedder_version="stub@2.0",
                ),
            ]
        )
        s.commit()

    with Session() as s:
        chunk = s.get(Chunk, "c1")
        assert chunk is not None
        assert chunk.parent_id == "p1"
        assert chunk.search_text == "context\n\nchild"
        assert {e.embedder_version for e in chunk.embeddings} == {"stub@1.0", "stub@2.0"}
