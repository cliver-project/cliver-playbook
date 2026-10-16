"""Opaque bearer tokens: issuance, verification, revocation (ADR-0004).

One physical table (`auth_tokens`), three logical kinds:

    kind          client_id     expires_at      label
    ------------  ------------  --------------  -----------------
    web session   NULL          now + 30 days   "" (empty)
    static token  NULL          NULL (never)    non-empty (e.g. "mcp-cli")
    oauth access  SET           now + TTL       ""

Tokens are 256-bit random values; only their SHA-256 hex digest is stored, so a
database leak does not leak usable credentials. A token by itself carries no
claims — everything (user, roles, permissions, expiry) is resolved from the
database on every request. That costs one indexed lookup per request and buys
instant, stateless revocation.

**Predicate discipline** (the security-critical part, mirrored by tests):
every statement that targets one kind MUST filter on that kind's discriminator
columns. `rotate_static_token` revokes only rows matching
`client_id IS NULL AND expires_at IS NULL AND label = :label`; OAuth paths
always carry `client_id = :client_id`. A predicate missing one discriminator is
how one kind's operation accidentally revokes another kind's tokens — e.g. a
static-token rotation wiping the user's browser sessions, or an OAuth
revocation killing static API tokens. Cross-kind isolation is enforced by
`test_rbac.py::token_kind_isolation`.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.models.entities import AuthToken, OauthRefreshToken

# Touching last_used_at on every request is one UPDATE per API call; throttled
# to at most one write per token per minute, which keeps request logs useful
# without meaningful write amplification.
_LAST_USED_THROTTLE = timedelta(seconds=60)


def hash_token(token: str) -> str:
    """SHA-256 hex digest — the only form ever written to the database."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> str:
    """256 bits of entropy, URL-safe. Plaintext exists once, at issuance."""
    return secrets.token_urlsafe(32)


async def issue_web_token(
    db: AsyncSession, *, user_id: int, ip: str = "", user_agent: str = ""
) -> str:
    """Issue a browser-session token: expiring, unlabeled, not bound to a client."""
    settings = get_settings()
    token = generate_token()
    db.add(
        AuthToken(
            user_id=user_id,
            token_hash=hash_token(token),
            label="",
            client_id=None,
            expires_at=utcnow() + timedelta(days=settings.token_ttl_days),
            created_ip=ip[:64],
            created_user_agent=user_agent[:256],
        )
    )
    await db.flush()
    return token


async def rotate_static_token(
    db: AsyncSession, *, user_id: int, label: str, ip: str = "", user_agent: str = ""
) -> tuple[str, int]:
    """Issue a non-expiring static token under `label`, replacing any previous
    token the user holds under the SAME label (one live token per label).

    Guard: the revoke predicate carries the full static-kind discriminator
    (`client_id IS NULL AND expires_at IS NULL AND label = :label`) so it can
    never touch web sessions (label "" + expiry) or OAuth access tokens
    (client_id set).
    """
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.label == label,
            AuthToken.client_id.is_(None),
            AuthToken.expires_at.is_(None),
            AuthToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    token = generate_token()
    row = AuthToken(
        user_id=user_id,
        token_hash=hash_token(token),
        label=label[:100],
        client_id=None,
        expires_at=None,  # static tokens never expire; revoke or rotate instead
        created_ip=ip[:64],
        created_user_agent=user_agent[:256],
    )
    db.add(row)
    await db.flush()
    return token, row.id


async def issue_oauth_access_token(
    db: AsyncSession,
    *,
    user_id: int,
    client_id: str,
    expires_at: datetime,
    ip: str = "",
    user_agent: str = "",
) -> tuple[str, int]:
    """Issue an OAuth access token for an AI-agent/API client (ADR-0005).

    `client_id` SET is what marks this kind; the OAuth provider (oauth21.py)
    is the only caller. Short TTL per RFC 9700 guidance.
    """
    token = generate_token()
    row = AuthToken(
        user_id=user_id,
        token_hash=hash_token(token),
        label="",
        client_id=client_id,
        expires_at=expires_at,
        created_ip=ip[:64],
        created_user_agent=user_agent[:256],
    )
    db.add(row)
    await db.flush()
    return token, row.id


async def verify_bearer(db: AsyncSession, token: str) -> AuthToken | None:
    """Resolve a bearer token to its row, or None for unknown/expired/revoked.

    Kind-agnostic by design: web, static, and OAuth access tokens all
    authenticate a request; authorization (what the bearer may do) is RBAC's
    job, checked after this lookup. Expiry only applies where `expires_at` is
    set — static tokens have none.
    """
    row = (
        await db.execute(select(AuthToken).where(AuthToken.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= utcnow():
        return None
    if row.last_used_at is None or (utcnow() - row.last_used_at) > _LAST_USED_THROTTLE:
        await db.execute(
            update(AuthToken).where(AuthToken.id == row.id).values(last_used_at=utcnow())
        )
    return row


async def revoke_all_for_user(db: AsyncSession, user_id: int) -> int:
    """Revoke every credential of every kind for a user.

    Used on password change (the owner must re-authenticate everywhere),
    admin-forced reset, deactivation, and force-logout. Covers BOTH token
    stores:

    - `auth_tokens` — web sessions, static tokens, OAuth access tokens
      (one table, three kinds; no discriminator filter here on purpose:
      every kind must die).
    - `oauth_refresh_tokens` — without this, revoking access tokens is
      theater: the client's next refresh rotation would mint a fresh one
      and the "session" would survive the password change. Revoked rows
      keep `replaced_by_id` NULL = the manual-revoke shape (silently
      invalid on replay, no family-cascade signal — this IS the cascade).

    Returns the number of `auth_tokens` rows revoked (the user-visible
    session count); refresh rows are counted separately by callers that
    audit them.
    """
    now = utcnow()
    result = await db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.execute(
        update(OauthRefreshToken)
        .where(OauthRefreshToken.user_id == user_id, OauthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount or 0


async def revoke_token_by_id(db: AsyncSession, token_id: int) -> bool:
    """Revoke one token row (user-facing 'log out this device')."""
    result = await db.execute(
        update(AuthToken)
        .where(AuthToken.id == token_id, AuthToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return (result.rowcount or 0) > 0
