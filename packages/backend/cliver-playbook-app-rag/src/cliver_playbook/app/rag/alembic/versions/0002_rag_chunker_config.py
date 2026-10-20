"""Add the per-document chunker configuration column.

Revision ID: 0002_rag_chunker_config
Revises: 0001_rag_initial
Create Date: 2026-10-19

``chunker_config`` is the effective configuration that produced the
current chunks: the chunker implementation version, the size/overlap
budget and the validated chunker options. It is 1:1 with the document
row and is replaced atomically on re-upload, so a fourth table would add
a join without enforcing a new invariant. The server default keeps rows
written outside the ORM valid and makes the column addition safe on an
existing database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_rag_chunker_config"
down_revision = "0001_rag_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column(
            "chunker_config",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rag_documents", "chunker_config")
