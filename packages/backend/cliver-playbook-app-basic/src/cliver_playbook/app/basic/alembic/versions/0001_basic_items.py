"""Basic package base schema: the demo `items` table.

This revision is the root of THIS package's migration chain. The chain lives
entirely inside cliver-playbook-app-basic: its head is tracked in the
``alembic_version_basic`` table, and packages built on top of basic own their
own chains and version tables (ADR-0015) — no cross-package down_revision
links, so packages are applied in dependency order and evolve independently.

The items table backs a runnable example of the full CRUD slice. A project
that does not need item management deletes it together with the rest of the
demo (see the package README).

Revision ID: 0001_basic_items
Revises: -
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_basic_items"
down_revision: str | Sequence[str] | None = None
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
