"""Initial RAG schema: documents, chunks, embeddings, pgvector extension.

Revision ID: 0001_rag_initial
Revises:
Create Date: 2026-10-18

The first DDL is ``CREATE EXTENSION IF NOT EXISTS vector`` — the rag
package is the only one that needs pgvector, so the extension load
lives here rather than in a shared init script. The dev Postgres
container ships the extension files; the extension itself is
created on demand.

The HNSW index uses ``vector_cosine_ops`` because every BGE-M3 and
Voyage embedding the system produces is L2-normalized at write time
(Embedding.embed normalizes by default), so cosine and inner product
are interchangeable and cosine is the conventional surface.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_rag_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_uri", sa.String(1024), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("chunker_id", sa.String(64), nullable=False),
        sa.Column("embedder_id", sa.String(64), nullable=False),
        sa.Column("dim", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("rag_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "rag_chunks_document_id_ordinal_idx",
        "rag_chunks",
        ["document_id", "ordinal"],
    )

    # rag_chunk_embeddings — the column type is VECTOR(1024), the
    # default for BGE-M3 (1024-d) and the smallest denomenator the
    # hosted providers ship. The Retriever / Embedder registry should
    # reject a dim mismatch at write time; if a project standardises
    # on a different dim, an ALTER is cheap (pgvector supports it
    # without rebuilding the table for dims <= 2000).
    op.execute(
        "CREATE TABLE rag_chunk_embeddings ("
        "  chunk_id varchar(64) PRIMARY KEY REFERENCES rag_chunks(id) ON DELETE CASCADE,"
        "  embedding vector(1024),"
        "  sparse_lexical jsonb,"
        "  embedder_version varchar(64) NOT NULL"
        ")"
    )
    op.execute(
        "CREATE INDEX rag_chunk_embeddings_hnsw_idx ON rag_chunk_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX rag_chunk_embeddings_sparse_idx ON rag_chunk_embeddings "
        "USING gin (sparse_lexical)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS rag_chunk_embeddings_sparse_idx")
    op.execute("DROP INDEX IF EXISTS rag_chunk_embeddings_hnsw_idx")
    op.execute("DROP TABLE IF EXISTS rag_chunk_embeddings")
    op.execute("DROP INDEX IF EXISTS rag_chunks_document_id_ordinal_idx")
    op.execute("DROP TABLE IF EXISTS rag_chunks")
    op.execute("DROP TABLE IF EXISTS rag_documents")
    # We intentionally do not drop the vector extension — other
    # databases on the same Postgres cluster may use it.
