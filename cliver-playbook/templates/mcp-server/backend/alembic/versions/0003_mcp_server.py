"""Phase 3 anchor: the MCP server's first alembic revision.

This migration is intentionally a no-op structurally. The MCP template
reuses the user-management ``audit_logs`` and ``auth_tokens`` tables
rather than introducing its own, so there is nothing new to create in
v1. The revision exists so that:

1. ``alembic upgrade head`` in an MCP-template project lands at this
   revision, and ``alembic downgrade -1`` rolls back to ``0002_user_management``
   cleanly (a no-op downgrade is also fine).
2. Future MCP-owned tables (e.g. an ``mcp_tool_registrations`` catalog
   for the tool namespacing story, or a per-tool rate-limit table)
   have a natural down_revision chain anchor that does not require
   editing 0002 or earlier.

Why not just drop the migration entirely? The user-management template
chains ``0001 -> 0002``; adding a third template downstream requires
a third revision that depends on ``0002``. Skipping the revision
forces ``down_revision = "0002_user_management"`` to live somewhere —
either in this file or in the first future migration that needs a
schema. A no-op anchor is the cleaner of the two: the chain has a
named endpoint, and a follow-up migration can simply bump its
``revision`` / ``down_revision`` without renaming anything.

Revision ID: ``0003_mcp_server``
Revises: ``0002_user_management``
Create Date: 2026-10-16
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0003_mcp_server"
down_revision = "0002_user_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No structural changes — see module docstring."""
    # The ``pass`` keeps the migration callable from alembic's perspective
    # while signaling intent: future MCP-owned tables will be added here,
    # not in 0002 or earlier.
    return


def downgrade() -> None:
    """No structural changes to roll back."""
    return
