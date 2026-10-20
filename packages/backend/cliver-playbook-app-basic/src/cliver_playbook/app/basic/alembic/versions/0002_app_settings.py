"""Runtime settings overrides: one row per module-owned section.

See ADR-0021. The table stores only values an administrator changed at
runtime; environment and ``.env`` entries still win over them, and secrets are
never written here.

Revision ID: 0002_app_settings
Revises: 0001_basic_items
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_app_settings"
down_revision: str | Sequence[str] | None = "0001_basic_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("section", sa.String(length=64), primary_key=True),
        sa.Column(
            "values",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # No FK to users: this package cannot depend on the identity package.
        # The id is informational (who last changed the section).
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
