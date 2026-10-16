"""ORM entities.

The identity domain (ADR-0003/0004/0005): RBAC tables, OIDC identity linking,
OAuth 2.1 provider tables, and the unified token table.

These tables all live in the `user` package's migration chain and share the
`basic` package's declarative base, so metadata is process-wide while each
package still migrates and owns its own tables (ADR-0015). The demo `Item`
entity lives in the `basic` package.

Guard invariants worth restating (enforced in `cliver_playbook.app.user.auth.tokens` and the OAuth
provider, mirrored by tests):

- `AuthToken` rows come in exactly three kinds distinguished by `client_id` /
  `expires_at` / `label` (ADR-0004):
    web session   client_id NULL, expires_at +30d, label ''
    static token  client_id NULL, expires_at NULL,  label set
    oauth access  client_id SET,   expires_at +TTL
  Any query that targets one kind MUST filter on those discriminator columns —
  e.g. static-token rotation always adds `client_id IS NULL`, OAuth operations
  always carry `client_id`. Cross-kind predicates are how tokens get revoked
  by accident.
- OAuth secrets are stored **hashed** (SHA-256) everywhere: `AuthToken.token_hash`,
  `OauthCode.code_hash`, `OauthRefreshToken.token_hash`. The single exception is
  `OauthClient.client_secret`, stored plaintext because the SDK's client
  authenticator compares it verbatim (RFC 7591 confidential clients) — it is never
  written to audit rows or logs.

All timestamps are `TIMESTAMPTZ` (`DateTime(timezone=True)`) — declared explicitly
on every column so Alembic autogenerate cannot drift to naive timestamps.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cliver_playbook.app.basic.db.base import Base

# ---------------------------------------------------------------------------
# RBAC core (ADR-0003)
# ---------------------------------------------------------------------------


class User(Base):
    """Application user. `password_hash == ""` marks an OIDC-only account."""

    __tablename__ = "users"
    __table_args__ = (
        # Constraints are named explicitly so model and migration DDL can never
        # drift apart on PostgreSQL's auto-generated names.
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Free-form contact number: international formats vary too much to
    # validate server-side, and it is NOT unique (households, switchboards).
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Role(Base):
    """A named bundle of permissions. Seeded roles carry `is_system` and cannot be deleted."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_roles_code"),)

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserRole(Base):
    """User <-> role assignment (many-to-many), with an audit trail of who granted it."""

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # SET NULL keeps the grant row's history readable after the granting admin is gone.
    granted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RolePermission(Base):
    """Role <-> permission-code binding. Codes are validated against the code catalog."""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# OIDC identity linking
# ---------------------------------------------------------------------------


class OauthIdentity(Base):
    """An external IdP identity (provider + subject) linked to a local user."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        # One IdP account maps to exactly one local user; login looks this pair up.
        UniqueConstraint("provider", "subject", name="uq_oauth_identities_provider_subject"),
        Index("ix_oauth_identities_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# OAuth 2.1 provider (ADR-0005) — for AI-agent / API clients
# ---------------------------------------------------------------------------


class OauthClient(Base):
    """A client registered via RFC 7591 dynamic registration (or seeded manually)."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Plaintext by necessity (SDK compares verbatim); never audited, never logged.
    client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Epoch seconds, the RFC 7591 wire format. NULL = no expiry.
    client_id_issued_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    client_secret_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    # Full OAuthClientInformation dump minus the secret — lossless round-trip on load.
    client_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=func.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OauthCode(Base):
    """One-time authorization code. `used_at` is the atomic-claim guard."""

    __tablename__ = "oauth_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_oauth_codes_code_hash"),
        # Expiry scans (cleanup jobs) walk this index.
        Index("ix_oauth_codes_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OauthRefreshToken(Base):
    """One-time rotating refresh token.

    Rotation pointer semantics: `revoked_at` set with `replaced_by_id` NULL means a
    manual /revoke; `revoked_at` set with `replaced_by_id` pointing at the successor
    means it was consumed by rotation — presenting it again is a replay signal.
    """

    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_token_hash"),
        Index("ix_oauth_refresh_tokens_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("oauth_refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# Tokens (ADR-0004: one table, three kinds) and audit
# ---------------------------------------------------------------------------


class AuthToken(Base):
    """Opaque bearer tokens, SHA-256 hashed. See module docstring for the kind rules."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
        # Revocation by user (password change, force logout) walks this index.
        Index("ix_auth_tokens_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    # Discriminators — every query touching one kind filters on these.
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_ip: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    created_user_agent: Mapped[str] = mapped_column(String(256), nullable=False, server_default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    """Unified audit trail: auth events, admin operations, MCP tool calls."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        # Both list views filter/sort on these.
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the event acted on, e.g. "user:3", "role:admin", an oauth client_id.
    target: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    error: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    # Sanitized (truncated) arguments/result metadata — see cliver_playbook.app.user.auth.audit.
    detail: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=func.text("'{}'::jsonb")
    )
    ip: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    user_agent: Mapped[str] = mapped_column(String(256), nullable=False, server_default="")
