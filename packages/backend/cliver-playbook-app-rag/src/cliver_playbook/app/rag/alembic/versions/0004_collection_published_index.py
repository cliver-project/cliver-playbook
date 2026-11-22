"""Scope the published-document uniqueness to its collection.

Revision ID: 0004_collection_published_index
Revises: 0003_rag_governance_primitives
Create Date: 2026-11-22

A logical document id is unique within a collection, not globally: two
projects may both call a document ``policy.pdf``. The original partial
index enforced uniqueness on ``logical_id`` alone, so publishing the
second project's copy failed with a unique violation even though the
rows belonged to different collections. The index now includes
``collection_id``, matching the identity the ingestion pipeline uses.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_collection_published_index"
down_revision = "0003_rag_governance_primitives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_rag_documents_published_logical_id", table_name="rag_documents")
    op.create_index(
        "uq_rag_documents_published_collection_logical",
        "rag_documents",
        ["collection_id", "logical_id"],
        unique=True,
        postgresql_where=sa.text("published"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_rag_documents_published_collection_logical",
        table_name="rag_documents",
    )
    op.create_index(
        "uq_rag_documents_published_logical_id",
        "rag_documents",
        ["logical_id"],
        unique=True,
        postgresql_where=sa.text("published"),
    )
