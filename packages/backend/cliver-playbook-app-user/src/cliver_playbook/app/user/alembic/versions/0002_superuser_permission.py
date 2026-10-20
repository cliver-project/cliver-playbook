"""Pin the seeded ``admin`` role to the superuser wildcard.

Before ADR-0021 the migration seed copied every catalog code into
``role_permissions`` at install time. Codes registered later by a composing
package (``mcp:*`` today, anything tomorrow) never reached an existing admin
role, so the administrator silently lost access to new surfaces. The wildcard
``*`` is evaluated at request time and covers codes that did not exist when
the role was created.

This revision makes the invariant true for databases that were seeded the old
way: the admin role keeps exactly one binding, ``*``. Fresh databases already
get ``*`` from migration 0001 (the catalog literal includes it); this
revision is then a no-op for them.

Revision ID: 0002_superuser_permission
Revises: 0001_user_management
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# The catalog is code (ADR-0003); the downgrade restores the pre-ADR-0021
# representation by enumerating it live, exactly like migration 0001's seed.
from cliver_playbook.app.user.auth.permissions import ALL_PERMISSIONS, permission_catalog

revision: str = "0002_superuser_permission"
down_revision: str | Sequence[str] | None = "0001_user_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: a fresh install already has the wildcard from 0001's seed.
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_code) "
            "SELECT id, :code FROM roles WHERE code = 'admin' "
            "ON CONFLICT DO NOTHING"
        ).bindparams(code=ALL_PERMISSIONS)
    )
    # The wildcard subsumes every enumerated grant; keeping them would make
    # "the admin role holds exactly ['*']" untrue and bloat the role view.
    op.execute(
        sa.text(
            "DELETE FROM role_permissions "
            "WHERE permission_code <> :code "
            "AND role_id IN (SELECT id FROM roles WHERE code = 'admin')"
        ).bindparams(code=ALL_PERMISSIONS)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions "
            "WHERE permission_code = :code "
            "AND role_id IN (SELECT id FROM roles WHERE code = 'admin')"
        ).bindparams(code=ALL_PERMISSIONS)
    )
    # Restore the pre-wildcard representation: every catalog code except the
    # wildcard itself.
    for entry in permission_catalog():
        if entry.code == ALL_PERMISSIONS:
            continue
        op.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_code) "
                "SELECT id, :code FROM roles WHERE code = 'admin' "
                "ON CONFLICT DO NOTHING"
            ).bindparams(code=entry.code)
        )
