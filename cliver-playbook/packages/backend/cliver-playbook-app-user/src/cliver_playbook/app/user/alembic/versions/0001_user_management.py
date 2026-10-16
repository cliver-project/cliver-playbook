"""Identity domain: RBAC, OIDC linking, OAuth 2.1 provider, tokens, audit.

Tables (see cliver_playbook.app.user.models.entities for column-level documentation):

    users, roles, user_roles, role_permissions        RBAC core (ADR-0003)
    oauth_identities                                  OIDC account linking
    oauth_clients, oauth_codes,
    oauth_refresh_tokens                              OAuth 2.1 provider (ADR-0005)
    auth_tokens                                       one table, three token
                                                      kinds (ADR-0004)
    audit_logs                                        unified audit trail

Seeds (idempotent-ish: guarded by NOT EXISTS so a re-run on a partially
migrated database does not duplicate rows) — ONLINE ONLY: an offline run
(`--sql`) emits the schema without the seed rows, since it has no connection
to check against and reads the initial password from settings:

    role `admin` (is_system, ALL catalog permissions)
    role `user`  (is_system, no permissions — the baseline every account gets)
    user  `admin` (must_change_password=TRUE; password from
          CLIVER_INITIAL_ADMIN_PASSWORD or generated-and-printed-once)

The seed imports the permission catalog and the password hasher from this
package on purpose: the catalog is code (ADR-0003), so a database seeded by
an old migration and an app built from new code can never disagree about
which permissions exist — they read the same tuple.

This is the first revision of the `user` package's own chain (ADR-0015): it
has no down_revision and is tracked separately from the `basic` package's
chain, in the `alembic_version_user` version table.

Revision ID: 0001_user_management
Create Date: 2026-10-15
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# Single source of truth for the seeded permission list and password format.
# Alembic runs on the sync driver, and both helpers are plain sync functions.
from cliver_playbook.app.user.auth.passwords import hash_password
from cliver_playbook.app.user.auth.permissions import permission_catalog
from cliver_playbook.app.user.settings import get_settings

revision: str = "0001_user_management"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # RBAC core
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.BigInteger(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "granted_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.BigInteger(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission_code", sa.String(length=64), primary_key=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # OIDC identity linking
    # ------------------------------------------------------------------
    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("provider", "subject", name="uq_oauth_identities_provider_subject"),
    )
    op.create_index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])

    # ------------------------------------------------------------------
    # OAuth 2.1 provider
    # ------------------------------------------------------------------
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=64), primary_key=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
        sa.Column("client_id_issued_at", sa.BigInteger(), nullable=True),
        sa.Column("client_secret_expires_at", sa.BigInteger(), nullable=True),
        sa.Column("client_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column(
            "client_metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "oauth_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column(
            "redirect_uri_provided_explicitly",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code_hash", name="uq_oauth_codes_code_hash"),
    )
    op.create_index("ix_oauth_codes_expires_at", "oauth_codes", ["expires_at"])

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by_id",
            sa.BigInteger(),
            sa.ForeignKey("oauth_refresh_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_token_hash"),
    )
    op.create_index("ix_oauth_refresh_tokens_expires_at", "oauth_refresh_tokens", ["expires_at"])

    # ------------------------------------------------------------------
    # Tokens and audit
    # ------------------------------------------------------------------
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_user_agent", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(length=256), nullable=False, server_default=""),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])

    _seed()


def _seed() -> None:
    """Seed system roles, the admin account, and the admin permission set."""
    if op.get_context().as_sql:
        # Offline mode (`--sql`) renders DDL for review: there is no
        # connection to check existing rows against, the permission catalog
        # is code rather than data, and the initial password comes from
        # runtime settings. The emitted script therefore carries the schema
        # only; seed rows appear when the chain is applied online
        # (run_migrations_online), which is the entry point to use for a real
        # deployment — it is the only one that both migrates and seeds.
        op.execute("-- seed skipped: run the online migration to seed roles and admin")
        return
    conn = op.get_bind()

    if conn.execute(sa.text("SELECT 1 FROM roles WHERE code = 'admin'")).scalar() is None:
        admin_role_id = conn.execute(
            sa.text(
                "INSERT INTO roles (code, name, description, is_system) "
                "VALUES ('admin', 'Administrator', 'All permissions (seeded)', true) "
                "RETURNING id"
            )
        ).scalar_one()
        if conn.execute(sa.text("SELECT 1 FROM roles WHERE code = 'user'")).scalar() is None:
            conn.execute(
                sa.text(
                    "INSERT INTO roles (code, name, description, is_system) "
                    "VALUES ('user', 'User', 'Baseline authenticated role (seeded)', true)"
                )
            )
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_code) VALUES (:role_id, :code)"
            ),
            [
                {"role_id": admin_role_id, "code": p.code}
                for p in sorted(permission_catalog(), key=lambda p: p.code)
            ],
        )

        if conn.execute(sa.text("SELECT 1 FROM users WHERE username = 'admin'")).scalar() is None:
            # Read through the layered Settings (env > .env > app.yaml > field
            # default) instead of raw os.environ: the raw read never saw the
            # .env file, so the documented "set CLIVER_INITIAL_ADMIN_PASSWORD
            # in .env" setup silently fell back to a generated password.
            password = get_settings().initial_admin_password
            generated = not password
            if generated:
                password = secrets.token_urlsafe(9)
            admin_user_id = conn.execute(
                sa.text(
                    "INSERT INTO users "
                    "(username, email, password_hash, display_name, is_active, "
                    " must_change_password) "
                    "VALUES ('admin', NULL, :password_hash, 'Administrator', true, true) "
                    "RETURNING id"
                ),
                {"password_hash": hash_password(password)},
            ).scalar_one()
            conn.execute(
                sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                {"user_id": admin_user_id, "role_id": admin_role_id},
            )
            if generated:
                # Shown exactly once, here. The password exists nowhere else and
                # first login forces a change, so losing this output means
                # dropping and re-migrating the database.
                print("\n" + "=" * 62)
                print("Initial admin account (migration 0001_user_management seed)")
                print("  username: admin")
                print(f"  password: {password}")
                print("  shown once, not stored — first login forces a change")
                print("=" * 62 + "\n")


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("ix_oauth_refresh_tokens_expires_at", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index("ix_oauth_codes_expires_at", table_name="oauth_codes")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
    op.drop_index("ix_oauth_identities_user_id", table_name="oauth_identities")
    op.drop_table("oauth_identities")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
