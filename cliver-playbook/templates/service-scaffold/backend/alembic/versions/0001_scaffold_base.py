"""Scaffold base schema: the demo `items` table.

This revision is the root of the migration chain shared by every template
built on the service scaffold (ADR-0007). Later templates (user-management,
mcp-server) attach their revisions to this one, so the chain stays linear
when templates are applied in order.

Revision ID: 0001_scaffold_base
Revises: -
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_scaffold_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_items_created_at", "items", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_items_created_at", table_name="items")
    op.drop_table("items")
