"""Add the generic primitives the governance package builds on.

Revision ID: 0003_rag_governance_primitives
Revises: 0002_rag_chunker_config
Create Date: 2026-11-05

Four changes, all deliberately in the generic ``rag`` chain:

- Document lineage/access columns (``logical_id``, ``classification``,
  ``collection_id``, ``metadata``, ``published``, …). A plain upload
  leaves them NULL and keeps the v1 behaviour.
- ``rag_chunk_parents``: the original parent section the generator
  receives, while children carry the short retrieval representation.
- ``rag_chunks.search_text`` and the FK to the parent table.
- A composite ``(chunk_id, embedder_version)`` embedding key, so a model
  migration can re-embed without destroying the previous vectors.

The partial unique index ``uq_rag_documents_published_logical_id`` is
the database-level guarantee that at most one version of a logical
document is visible to retrieval. It is created here rather than from
ORM metadata because SQLite ignores the partial predicate and would
wrongly reject the staged versions the governance flow creates.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_rag_governance_primitives"
down_revision = "0002_rag_chunker_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_documents", sa.Column("logical_id", sa.String(128), nullable=True))
    op.add_column("rag_documents", sa.Column("classification", sa.Integer(), nullable=True))
    op.add_column("rag_documents", sa.Column("collection_id", sa.String(128), nullable=True))
    op.add_column(
        "rag_documents",
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "rag_documents",
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("rag_documents", sa.Column("pipeline_run_id", sa.String(64), nullable=True))
    op.add_column(
        "rag_documents",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("rag_documents", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column(
        "rag_documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rag_documents_logical_id", "rag_documents", ["logical_id"])
    op.create_index("ix_rag_documents_classification", "rag_documents", ["classification"])
    op.create_index("ix_rag_documents_collection_id", "rag_documents", ["collection_id"])
    op.create_index("ix_rag_documents_published", "rag_documents", ["published"])
    op.create_index("ix_rag_documents_pipeline_run_id", "rag_documents", ["pipeline_run_id"])

    op.create_table(
        "rag_chunk_parents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("rag_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_rag_chunk_parents_document_id", "rag_chunk_parents", ["document_id"])

    op.add_column("rag_chunks", sa.Column("search_text", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_rag_chunks_parent_id",
        "rag_chunks",
        "rag_chunk_parents",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # The v1 primary key allowed exactly one embedding per chunk. A
    # model migration needs the old vectors to stay readable while the
    # new ones are written, so the version joins the key.
    op.execute("ALTER TABLE rag_chunk_embeddings DROP CONSTRAINT rag_chunk_embeddings_pkey")
    op.execute(
        "ALTER TABLE rag_chunk_embeddings "
        "ADD CONSTRAINT rag_chunk_embeddings_pkey "
        "PRIMARY KEY (chunk_id, embedder_version)"
    )

    op.create_index(
        "uq_rag_documents_published_logical_id",
        "rag_documents",
        ["logical_id"],
        unique=True,
        postgresql_where=sa.text("published"),
    )
    op.create_index(
        "ix_rag_documents_collection_published",
        "rag_documents",
        ["collection_id", "published"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_documents_collection_published", table_name="rag_documents")
    op.drop_index("uq_rag_documents_published_logical_id", table_name="rag_documents")

    # Reverting the key is lossy: a chunk with several embedding
    # versions cannot be represented. Keep one row arbitrarily rather
    # than failing the downgrade.
    op.execute(
        "DELETE FROM rag_chunk_embeddings a USING rag_chunk_embeddings b "
        "WHERE a.chunk_id = b.chunk_id AND a.embedder_version <> b.embedder_version"
    )
    op.execute("ALTER TABLE rag_chunk_embeddings DROP CONSTRAINT rag_chunk_embeddings_pkey")
    op.execute(
        "ALTER TABLE rag_chunk_embeddings "
        "ADD CONSTRAINT rag_chunk_embeddings_pkey PRIMARY KEY (chunk_id)"
    )

    op.drop_constraint("fk_rag_chunks_parent_id", "rag_chunks", type_="foreignkey")
    op.drop_column("rag_chunks", "search_text")

    op.drop_index("ix_rag_chunk_parents_document_id", table_name="rag_chunk_parents")
    op.drop_table("rag_chunk_parents")

    op.drop_index("ix_rag_documents_pipeline_run_id", table_name="rag_documents")
    op.drop_index("ix_rag_documents_published", table_name="rag_documents")
    op.drop_index("ix_rag_documents_collection_id", table_name="rag_documents")
    op.drop_index("ix_rag_documents_classification", table_name="rag_documents")
    op.drop_index("ix_rag_documents_logical_id", table_name="rag_documents")
    op.drop_column("rag_documents", "deleted_at")
    op.drop_column("rag_documents", "content_hash")
    op.drop_column("rag_documents", "source_updated_at")
    op.drop_column("rag_documents", "pipeline_run_id")
    op.drop_column("rag_documents", "published")
    op.drop_column("rag_documents", "metadata")
    op.drop_column("rag_documents", "collection_id")
    op.drop_column("rag_documents", "classification")
    op.drop_column("rag_documents", "logical_id")
