"""Schema smoke test: the rag tables exist and carry the expected columns.

The test runs against an in-memory SQLite database so it doesn't need
the dev Postgres container. The pgvector type falls back to Text() on
SQLite; the same ORM model is used in production with the real vector
type. The test's job is to pin the column names and the document/chunk
relationship, not the embedding vector type.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cliver_playbook.app.rag.models.base import Base
from cliver_playbook.app.rag.models.entities import Chunk, ChunkEmbedding, Document


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


def test_documents_table_exists(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    assert "rag_documents" in insp.get_table_names()


def test_chunks_table_exists(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    assert "rag_chunks" in insp.get_table_names()


def test_chunk_embeddings_table_exists(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    assert "rag_chunk_embeddings" in insp.get_table_names()


def test_document_columns(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    cols = {c["name"] for c in insp.get_columns("rag_documents")}
    assert {
        "id",
        "title",
        "source_uri",
        "mime_type",
        "chunker_id",
        "embedder_id",
        "dim",
        "version",
        "status",
        "failure_reason",
        "chunk_count",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_chunk_columns(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    cols = {c["name"] for c in insp.get_columns("rag_chunks")}
    assert {
        "id",
        "document_id",
        "ordinal",
        "text",
        "token_count",
        "metadata",
        "parent_id",
        "created_at",
    }.issubset(cols)


def test_chunk_embedding_columns(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    cols = {c["name"] for c in insp.get_columns("rag_chunk_embeddings")}
    assert {"chunk_id", "embedding", "dim", "sparse_lexical", "embedder_version"}.issubset(cols)


def test_chunk_has_fk_to_document(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    fks = insp.get_foreign_keys("rag_chunks")
    assert any(fk["referred_table"] == "rag_documents" for fk in fks)


def test_chunk_embedding_has_fk_to_chunk(engine) -> None:
    insp = __import__("sqlalchemy").inspect(engine)
    fks = insp.get_foreign_keys("rag_chunk_embeddings")
    assert any(fk["referred_table"] == "rag_chunks" for fk in fks)


def test_round_trip_document_and_chunks(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as s:
        doc = Document(
            id="doc1",
            title="hello",
            source_uri="file:///tmp/hello.txt",
            mime_type="text/plain",
            chunker_id="recursive",
            embedder_id="stub",
            dim=64,
            status="indexed",
            chunk_count=2,
        )
        s.add(doc)
        s.flush()
        s.add(
            Chunk(
                id="c1",
                document_id="doc1",
                ordinal=0,
                text="hello world",
                token_count=2,
                metadata_json={"section_path": []},
            )
        )
        s.add(
            Chunk(
                id="c2",
                document_id="doc1",
                ordinal=1,
                text="another chunk",
                token_count=2,
                metadata_json={},
                parent_id="c1",
            )
        )
        s.flush()
        s.add(
            ChunkEmbedding(
                chunk_id="c1",
                embedding=[0.0, 0.0, 0.0, 0.0],
                dim=4,
                embedder_version="stub@1.0",
            )
        )
        s.commit()
    with Session() as s:
        doc = s.get(Document, "doc1")
        assert doc is not None
        assert doc.chunk_count == 2
        assert len(doc.chunks) == 2
        # ordinal ordering
        assert doc.chunks[0].ordinal == 0
        assert doc.chunks[1].parent_id == "c1"
