"""Reference products table.

Revision ID: 0001_products
Revises:
Create Date: 2026-01-01 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_products"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
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
    op.create_index("ix_products_created_at", "products", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_products_created_at", table_name="products")
    op.drop_table("products")
