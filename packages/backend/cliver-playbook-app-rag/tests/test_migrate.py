"""The rag migration chain actually runs when asked to.

This package's HTTP and service tests build their schema from the ORM
metadata, so they never exercise ``alembic/env.py``. That is exactly how a
missing module-level dispatch at the bottom of env.py went unnoticed: alembic
executed the file, the file defined the two migration functions, and then
exited without calling either — ``upgrade head`` reported success while
creating nothing.

Offline mode renders the same chain without connecting to a database, which
makes it a cheap guard for that class of failure: if the dispatch is missing,
no SQL is printed.
"""

from __future__ import annotations

from cliver_playbook.app.rag.alembic import run_migrations_offline


def test_offline_migration_renders_the_rag_schema(capsys) -> None:
    # A URL is required to select the dialect; offline mode never connects.
    run_migrations_offline("postgresql+psycopg://user:pass@127.0.0.1:5432/offline")

    sql = capsys.readouterr().out
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE rag_documents" in sql
    assert "chunker_config" in sql
    assert "CREATE TABLE rag_chunks" in sql
    assert "CREATE TABLE rag_chunk_embeddings" in sql
    assert "rag_chunk_embeddings_hnsw_1024_idx" in sql
    assert "alembic_version_rag" in sql


def test_offline_migration_renders_governance_primitives(capsys) -> None:
    run_migrations_offline("postgresql+psycopg://user:pass@127.0.0.1:5432/offline")

    sql = capsys.readouterr().out
    assert "CREATE TABLE rag_chunk_parents" in sql
    assert "logical_id" in sql
    assert "search_text" in sql
    assert "PRIMARY KEY (chunk_id, embedder_version)" in sql
    assert "WHERE published" in sql


def test_published_uniqueness_is_scoped_to_the_collection(capsys) -> None:
    run_migrations_offline("postgresql+psycopg://user:pass@127.0.0.1:5432/offline")

    sql = capsys.readouterr().out
    assert "DROP INDEX uq_rag_documents_published_logical_id" in sql
    assert (
        "CREATE UNIQUE INDEX uq_rag_documents_published_collection_logical "
        "ON rag_documents (collection_id, logical_id) WHERE published"
    ) in sql
