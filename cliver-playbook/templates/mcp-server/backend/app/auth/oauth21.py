"""OAuth 2.1 authorization server for AI-agent / API clients (ADR-0005).

Shape: the official `mcp` SDK's OAuthAuthorizationServerProvider implementation
plus stateless hand-off helpers. The provider surfaces standard OAuth routes
(authorization code + PKCE S256, RFC 7591 dynamic client registration,
protected-resource metadata, refresh rotation, RFC 7009 revocation) on the
FastAPI app — see `mount_oauth_routes`.

The static long-lived token path (label rotation in `app.auth.tokens`) is a
separate lane that OAuth never touches and vice versa: every OAuth predicate
carries `client_id`, every static predicate carries `client_id IS NULL`.

Design points ported verbatim from a hardened production predecessor — treat
them as load-bearing (each has a regression test):

- **Access tokens reuse `auth_tokens`** (client_id SET, +TTL) — one revocation
  path for everything a user holds.
- **Refresh tokens rotate one-time**: `replaced_by_id` is the rotation pointer.
  It distinguishes "revoked via /revoke" (NULL pointer, silently invalid) from
  "consumed by rotation then replayed" (pointer set, defense triggers).
  Replay inside the grace window (`race_suspected` — tolerates network retries
  and concurrent refreshes) only audits; beyond it the whole (user, client)
  token family is revoked, as OAuth 2.1 requires.
- **The authorize->login hand-off is an HMAC-signed blob** (stateless, zero DB
  writes): signed when the SDK's /authorize redirects to the SPA, verified when
  the SPA posts credentials back — a tampered redirect_uri or injected
  code_challenge cannot survive that round trip.
- **`iss` must match byte-for-byte**: the issuer goes through a
  preserve-empty-path URL adapter so `http://host:port` keeps no trailing
  slash; the metadata document, PRM authorization_servers, and the redirect's
  iss parameter all derive from that one normalized value (agent clients
  compare them character by character — empirically, including the SDK).
- **Non-HTTPS, non-loopback issuers** make the SDK's route factory raise
  ValueError; we log a warning and mount nothing rather than refuse to start —
  the static-token path must always work.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl, ConfigDict, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import write_audit
from app.auth.tokens import issue_oauth_access_token
from app.core.config import get_settings
from app.core.timeutil import utcnow
from app.db.session import SessionLocal
from app.models.entities import AuthToken, OauthClient, OauthCode, OauthRefreshToken, User

logger = logging.getLogger("cliver_app.oauth21")

REFRESH_PREFIX = "cliver_rt_"  # distinguishes refresh plaintext from access tokens
_BLOB_DOMAIN = "oauth-blob:"  # HMAC domain prefix (isolates blob signatures)

# Same as the SDK's mcp/client/auth/oauth2.py: an empty path gets no trailing
# slash — the foundation of byte-for-byte iss equality.
_URL_ADAPTER = TypeAdapter(AnyHttpUrl, config=ConfigDict(url_preserve_empty_path=True))

# Client redirect targets may be custom schemes (deep links): parse them with
# AnyUrl exactly like the SDK models do. (A production regression found these
# 500-ing when AnyHttpUrl validation was applied instead.)
_ANY_URL_ADAPTER = TypeAdapter(AnyUrl)

# ip/user-agent of the current HTTP request, set by RequestMetaMiddleware —
# provider methods get no Request argument from the SDK.
_request_meta: ContextVar[tuple[str, str]] = ContextVar("oauth21_request_meta", default=("", ""))


def set_request_meta(ip: str, ua: str) -> None:
    _request_meta.set((ip or "", ua or ""))


def _meta() -> tuple[str, str]:
    return _request_meta.get()


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def http_url(text: str) -> AnyHttpUrl:
    """Parse with preserve_empty_path: `http://h:port` keeps no trailing slash."""
    return _URL_ADAPTER.validate_python(text)


def any_url(text: str) -> AnyUrl:
    """Lenient URL parse (custom schemes allowed) — client callback URLs only."""
    return _ANY_URL_ADAPTER.validate_python(text)


# ============ Settings snapshot ============


@dataclass(frozen=True)
class OAuthSettings:
    base_url: str  # canonical external base URL (no trailing slash)
    issuer: str  # == base_url; the single source for iss and metadata
    resource: str  # {base_url}/mcp — RFC 8707 resource indicator
    access_ttl: int  # seconds
    refresh_ttl: int  # seconds
    code_ttl: int  # seconds
    login_ttl: int  # login-blob lifetime, seconds
    replay_grace: int  # refresh replay grace window, seconds (0 = strict)


def load_oauth_settings(base_url: str | None = None) -> OAuthSettings:
    """Snapshot config: explicit base URL wins, else CLIVER_OAUTH21_ISSUER_URL,
    else the local dev default (an HTTP loopback issuer, which the SDK accepts)."""
    settings = get_settings()
    raw = (base_url or settings.oauth21_issuer_url or "http://127.0.0.1:8000").strip()
    canonical = str(http_url(raw.rstrip("/")))
    return OAuthSettings(
        base_url=canonical,
        issuer=canonical,
        resource=canonical + "/mcp",
        access_ttl=max(1, settings.oauth21_access_ttl_seconds),
        refresh_ttl=max(1, settings.oauth21_refresh_ttl_seconds),
        code_ttl=max(1, settings.oauth21_code_ttl_seconds),
        login_ttl=max(1, settings.oauth21_login_ttl_seconds),
        replay_grace=max(0, settings.oauth21_replay_grace_seconds),
    )


def registration_options():
    """DCR options — shared by create_auth_routes and the shadow metadata."""
    from mcp.server.auth.settings import ClientRegistrationOptions

    return ClientRegistrationOptions(
        enabled=True,
        valid_scopes=["mcp", "offline_access"],
        default_scopes=["mcp", "offline_access"],
    )


def revocation_options():
    from mcp.server.auth.settings import RevocationOptions

    return RevocationOptions(enabled=True)


def build_as_metadata(settings: OAuthSettings) -> dict:
    """AS metadata document (shadow route; same source as the SDK's own).

    Two patches:
    - token_endpoint_auth_methods_supported gains "none": the SDK omits it,
      but DCR accepts public clients that register with "none" — without the
      patch their client metadata fails validation.
    - authorization_response_iss_parameter_supported=True: we always return
      iss, so advertise it.
    """
    from mcp.server.auth.routes import build_metadata

    metadata = build_metadata(
        http_url(settings.issuer), None, registration_options(), revocation_options()
    )
    methods = list(metadata.token_endpoint_auth_methods_supported or [])
    if "none" not in methods:
        methods.append("none")
    metadata.token_endpoint_auth_methods_supported = methods
    metadata.authorization_response_iss_parameter_supported = True
    return metadata.model_dump(exclude_none=True, mode="json")


def build_prm(settings: OAuthSettings) -> dict:
    """Protected-resource metadata (the bare-path alias route; the /mcp-path
    variant comes from the SDK routes — both render the same values)."""
    from mcp.shared.auth import ProtectedResourceMetadata

    settings_app = get_settings()
    prm = ProtectedResourceMetadata(
        resource=http_url(settings.resource),
        authorization_servers=[http_url(settings.issuer)],
        scopes_supported=["mcp"],
        resource_name=settings_app.app_name,
    )
    return prm.model_dump(exclude_none=True, mode="json")


# ============ Login hand-off blob (HMAC-signed, stateless) ============


def _blob_secret() -> bytes:
    """HMAC key: explicit CLIVER_SECRET_KEY, else derived from the database URL
    (stable across restarts, zero config; rotating either invalidates
    outstanding blobs, which is acceptable for a 10-minute hand-off window)."""
    return get_settings().hmac_secret


def sign_login_blob(payload: dict) -> str:
    body = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        )
        .decode("ascii")
        .rstrip("=")
    )
    sig = hmac.new(
        _blob_secret(), (_BLOB_DOMAIN + body).encode("ascii"), hashlib.sha256
    ).hexdigest()[:32]
    return f"{body}.{sig}"


def verify_login_blob(blob: str) -> dict | None:
    """Signature + expiry check -> payload; None on any failure (no silent
    degradation, and callers must not reveal which check failed)."""
    body, _, sig = (blob or "").rpartition(".")
    if not body or not sig:
        return None
    expected = hmac.new(
        _blob_secret(), (_BLOB_DOMAIN + body).encode("ascii"), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:  # noqa: BLE001 — any malformation of a forged blob is invalid
        return None
    if not isinstance(payload, dict):
        return None
    try:
        exp = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return None
    if exp <= int(time.time()):
        return None
    return payload


async def client_display_name(client_id: str) -> str:
    """Client name for the authorize screen (empty if unknown — the caller
    provides fallback copy)."""
    async with SessionLocal() as db:
        name = (
            await db.execute(
                select(OauthClient.client_name).where(OauthClient.client_id == client_id)
            )
        ).scalar_one_or_none()
    return (name or "").strip()


# ============ Authorization code persistence ============


async def issue_authorization_code(
    settings: OAuthSettings, payload: dict, *, user_id: int
) -> str | None:
    """After successful login with a valid blob: store the authorization code,
    return the plaintext exactly once. None when the client no longer exists.

    Everything (scopes, challenge, redirect) comes from the VERIFIED blob, not
    from any form field — the signature is the tamper check.
    """
    client_id = str(payload.get("cid") or "")
    raw = "cliver_code_" + secrets.token_urlsafe(32)
    async with SessionLocal() as db:
        if (await db.get(OauthClient, client_id)) is None:
            return None
        db.add(
            OauthCode(
                code_hash=_sha256(raw),
                client_id=client_id,
                user_id=user_id,
                scopes=" ".join(payload.get("sc") or []),
                code_challenge=str(payload.get("cc") or ""),
                redirect_uri=str(payload.get("ru") or ""),
                redirect_uri_provided_explicitly=bool(payload.get("rep", True)),
                resource=payload.get("res"),
                expires_at=utcnow() + timedelta(seconds=settings.code_ttl),
            )
        )
        await db.commit()
    return raw


def build_authorization_redirect(settings: OAuthSettings, payload: dict, code: str) -> str:
    """302 back to the client: redirect_uri?code&state&iss — iss shares the
    exact normalized value the metadata exposes."""
    return construct_redirect_uri(
        str(payload.get("ru") or ""),
        code=code,
        state=payload.get("st"),
        iss=settings.issuer,
    )


# ============ Provider (9 methods) ============


async def _active_user(subject: str | None) -> dict | None:
    """subject (user id as string) -> active user; deactivated or
    must-change-password accounts are rejected (mirrors web 403 semantics)."""
    try:
        user_id = int(subject or "")
    except (TypeError, ValueError):
        return None
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active or user.must_change_password:
            return None
        return {"id": user.id, "username": user.username}


def _oauth_label(client_name: str) -> str:
    name = (client_name or "").strip()[:60] or "OAuth client"
    return f"{name} (OAuth)"


async def revoke_grant(db: AsyncSession, *, user_id: int, client_id: str) -> int:
    """Revoke one (user, client) grant on the CALLER's session — both halves:
    the refresh chain (future rotations) and live OAuth access tokens (the
    current requests). No commit; the caller owns the transaction, so an admin
    router can commit the revocation and its audit row atomically.

    Predicate discipline: both statements carry user_id AND client_id — they
    can never reach another pair's grants, nor web/static token rows (those
    have client_id IS NULL). Returns the number of refresh rows revoked.
    """
    now = utcnow()
    refresh = await db.execute(
        update(OauthRefreshToken)
        .where(
            OauthRefreshToken.user_id == user_id,
            OauthRefreshToken.client_id == client_id,
            OauthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.client_id == client_id,
            AuthToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return refresh.rowcount or 0


async def _revoke_family(user_id: int, client_id: str) -> None:
    """Revoke every refresh token and live OAuth access token for the
    (user, client) pair. Predicates carry client_id — static rows
    (client_id IS NULL) can never be touched. Double protection by design."""
    async with SessionLocal() as db:
        await revoke_grant(db, user_id=user_id, client_id=client_id)
        await db.commit()


class OAuthProvider(OAuthAuthorizationServerProvider):
    """Provider protocol implementation over async SQLAlchemy sessions."""

    def __init__(self, settings: OAuthSettings):
        self.s = settings

    # ---- Dynamic client registration (RFC 7591) ----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with SessionLocal() as db:
            row = await db.get(OauthClient, client_id)
            if row is None:
                return None
            data = dict(row.client_metadata or {})
            data["client_id"] = row.client_id
            if row.client_secret:
                data["client_secret"] = row.client_secret
            if row.client_id_issued_at is not None:
                data["client_id_issued_at"] = row.client_id_issued_at
            if row.client_secret_expires_at is not None:
                data["client_secret_expires_at"] = row.client_secret_expires_at
        try:
            return OAuthClientInformationFull.model_validate(data)
        except Exception:
            logger.exception("Unparseable OAuth client metadata (client_id=%s)", client_id)
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        dump = client_info.model_dump(mode="json", exclude_none=True)
        dump.pop("client_secret", None)  # separate column; never in metadata/audit
        dump.pop("issuer", None)
        redirect_uris = client_info.redirect_uris
        ip, ua = _meta()
        async with SessionLocal() as db:
            db.add(
                OauthClient(
                    client_id=client_info.client_id,
                    client_secret=client_info.client_secret,
                    client_id_issued_at=client_info.client_id_issued_at,
                    client_secret_expires_at=client_info.client_secret_expires_at,
                    client_name=(client_info.client_name or "")[:200],
                    client_metadata=dump,
                )
            )
            await db.commit()
            await write_audit(
                db,
                event="oauth.client.registered",
                target=client_info.client_id,
                detail={
                    "client_name": client_info.client_name or "",
                    "token_endpoint_auth_method": client_info.token_endpoint_auth_method,
                    "public_client": client_info.client_secret is None,
                    "redirect_uris": (
                        [str(u) for u in redirect_uris] if isinstance(redirect_uris, list) else []
                    ),
                },
                ip=ip,
                user_agent=ua,
            )
            await db.commit()

    # ---- Authorize endpoint -> browser login page ----

    async def authorize(self, client: OAuthClientInformationFull, params) -> str:
        if params.resource and params.resource.rstrip("/") != self.s.resource.rstrip("/"):
            raise AuthorizeError(
                error="invalid_target", error_description="resource is not this server"
            )
        scopes = [s for s in (params.scopes or []) if s]
        if not scopes:
            scopes = [s for s in (client.scope or "").split() if s] or ["mcp"]
        payload = {
            "v": 1,
            "cid": client.client_id,
            "cn": (client.client_name or "")[:100],
            "ru": str(params.redirect_uri),
            "rep": bool(params.redirect_uri_provided_explicitly),
            "cc": params.code_challenge,
            "sc": scopes,
            "st": params.state,
            "res": params.resource,
            "exp": int(time.time()) + self.s.login_ttl,
        }
        settings = get_settings()
        frontend = settings.web_base_url.rstrip("/")
        return f"{frontend}/oauth/authorize?oauth={quote(sign_login_blob(payload), safe='')}"

    # ---- Authorization code exchange ----

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(OauthCode).where(OauthCode.code_hash == _sha256(authorization_code))
                )
            ).scalar_one_or_none()
            if row is None or row.used_at is not None or row.client_id != client.client_id:
                return None
            if row.expires_at <= utcnow():
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=(row.scopes or "").split() or ["mcp"],
                expires_at=row.expires_at.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=any_url(row.redirect_uri),  # client callback may be a deep link
                redirect_uri_provided_explicitly=bool(row.redirect_uri_provided_explicitly),
                resource=row.resource,
                subject=str(row.user_id),
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        user = await _active_user(authorization_code.subject)
        if user is None:
            raise TokenError(
                error="invalid_grant",
                error_description="authorized user unavailable (inactive or must change password)",
            )
        # Atomic claim: of two concurrent exchanges only one wins the row.
        # (PKCE was already verified by the SDK handler before reaching here.)
        async with SessionLocal() as db:
            claimed = (
                await db.execute(
                    update(OauthCode)
                    .where(
                        OauthCode.code_hash == _sha256(authorization_code.code),
                        OauthCode.used_at.is_(None),
                    )
                    .values(used_at=utcnow())
                )
            ).rowcount
            await db.commit()
        if claimed != 1:
            raise TokenError(
                error="invalid_grant",
                error_description="authorization code already used or unknown",
            )

        scopes = [s for s in (authorization_code.scopes or []) if s] or ["mcp"]
        label = _oauth_label(client.client_name or "")
        ip, ua = _meta()
        expires_at = utcnow() + timedelta(seconds=self.s.access_ttl)
        async with SessionLocal() as db:
            raw_at, _ = await issue_oauth_access_token(
                db,
                user_id=user["id"],
                client_id=client.client_id,
                expires_at=expires_at,
                ip=ip,
                user_agent=ua,
            )
            raw_rt = REFRESH_PREFIX + secrets.token_urlsafe(32)
            db.add(
                OauthRefreshToken(
                    token_hash=_sha256(raw_rt),
                    client_id=client.client_id,
                    user_id=user["id"],
                    scopes=" ".join(scopes),
                    resource=authorization_code.resource,
                    expires_at=utcnow() + timedelta(seconds=self.s.refresh_ttl),
                )
            )
            await write_audit(
                db,
                event="oauth.token.issued",
                user_id=user["id"],
                username=user["username"],
                target=client.client_id,
                detail={
                    "label": label,
                    "scopes": scopes,
                    "expires_in": self.s.access_ttl,
                },
                ip=ip,
                user_agent=ua,
            )
            await db.commit()
        return OAuthToken(
            access_token=raw_at,
            token_type="Bearer",
            expires_in=self.s.access_ttl,
            scope=" ".join(scopes),
            refresh_token=raw_rt,
        )

    # ---- Refresh rotation (OAuth 2.1) ----

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(OauthRefreshToken).where(
                        OauthRefreshToken.token_hash == _sha256(refresh_token)
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.client_id != client.client_id:
                return None
            if row.revoked_at is not None:
                # replaced_by_id distinguishes manual /revoke (NULL pointer,
                # silently invalid) from consumed-by-rotation (pointer set —
                # presenting it again is a replay signal).
                replaced = row.replaced_by_id is not None
                revoked_age = (utcnow() - row.revoked_at).total_seconds()
                user_id, token_id = row.user_id, row.id
            elif row.expires_at <= utcnow():
                return None
            else:
                return RefreshToken(
                    token=refresh_token,
                    client_id=row.client_id,
                    scopes=(row.scopes or "").split() or ["mcp"],
                    expires_at=int(row.expires_at.timestamp()),
                    resource=row.resource,
                    subject=str(row.user_id),
                )

        if not replaced:
            return None
        ip, ua = _meta()
        if self.s.replay_grace and revoked_age <= self.s.replay_grace:
            # Inside the grace window: network retries / concurrent refreshes
            # trip this legitimately — audit only, do not revoke the chain.
            async with SessionLocal() as db:
                await write_audit(
                    db,
                    event="oauth.token.replay",
                    user_id=user_id,
                    ok=False,
                    error="replayed_refresh_token",
                    target=client.client_id,
                    detail={
                        "action": "race_suspected",
                        "token_id": token_id,
                        "age_seconds": int(revoked_age),
                    },
                    ip=ip,
                    user_agent=ua,
                )
                await db.commit()
            return None
        # Replay beyond grace: revoke the whole (user, client) family.
        await _revoke_family(user_id, client.client_id)
        async with SessionLocal() as db:
            await write_audit(
                db,
                event="oauth.token.replay",
                user_id=user_id,
                ok=False,
                error="replayed_refresh_token",
                target=client.client_id,
                detail={
                    "action": "chain_revoked",
                    "token_id": token_id,
                    "age_seconds": int(revoked_age),
                },
                ip=ip,
                user_agent=ua,
            )
            await db.commit()
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        user = await _active_user(refresh_token.subject)
        if user is None:
            # Inactive / must-change users get no rotation: the client's
            # invalid_grant leads it back to re-authorization, where the web
            # 403 explains why.
            raise TokenError(
                error="invalid_grant",
                error_description="authorized user unavailable (inactive or must change password)",
            )
        new_scopes = [s for s in (scopes or refresh_token.scopes or []) if s] or ["mcp"]
        raw_rt = REFRESH_PREFIX + secrets.token_urlsafe(32)
        async with SessionLocal() as db:
            new_row = OauthRefreshToken(
                token_hash=_sha256(raw_rt),
                client_id=client.client_id,
                user_id=user["id"],
                scopes=" ".join(new_scopes),
                resource=refresh_token.resource,
                expires_at=utcnow() + timedelta(seconds=self.s.refresh_ttl),
            )
            db.add(new_row)
            await db.flush()
            rotated = (
                await db.execute(
                    update(OauthRefreshToken)
                    .where(
                        OauthRefreshToken.token_hash == _sha256(refresh_token.token),
                        OauthRefreshToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=utcnow(), replaced_by_id=new_row.id)
                )
            ).rowcount
            if rotated != 1:
                await db.rollback()
                raise TokenError(
                    error="invalid_grant", error_description="refresh token already consumed"
                )
            await db.commit()

        label = _oauth_label(client.client_name or "")
        ip, ua = _meta()
        expires_at = utcnow() + timedelta(seconds=self.s.access_ttl)
        async with SessionLocal() as db:
            raw_at, _ = await issue_oauth_access_token(
                db,
                user_id=user["id"],
                client_id=client.client_id,
                expires_at=expires_at,
                ip=ip,
                user_agent=ua,
            )
            await write_audit(
                db,
                event="oauth.token.refreshed",
                user_id=user["id"],
                username=user["username"],
                target=client.client_id,
                detail={"label": label, "scopes": new_scopes, "expires_in": self.s.access_ttl},
                ip=ip,
                user_agent=ua,
            )
            await db.commit()
        return OAuthToken(
            access_token=raw_at,
            token_type="Bearer",
            expires_in=self.s.access_ttl,
            scope=" ".join(new_scopes),
            refresh_token=raw_rt,
        )

    # ---- /revoke support ----

    async def load_access_token(self, token: str) -> AccessToken | None:
        if not token or token.startswith(REFRESH_PREFIX):
            return None
        async with SessionLocal() as db:
            row = (
                await db.execute(select(AuthToken).where(AuthToken.token_hash == _sha256(token)))
            ).scalar_one_or_none()
            if row is None or row.revoked_at is not None or row.client_id is None:
                return None  # static tokens (client_id NULL) are not OAuth's to revoke
            if row.expires_at is not None and row.expires_at <= utcnow():
                return None
            expires_at = int(row.expires_at.timestamp()) if row.expires_at is not None else None
            client_id, user_id = row.client_id, row.user_id
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=[],
            expires_at=expires_at,
            resource=None,
            subject=str(user_id),
        )

    async def revoke_token(self, token) -> None:
        ip, ua = _meta()
        if isinstance(token, RefreshToken):
            async with SessionLocal() as db:
                row = (
                    await db.execute(
                        select(OauthRefreshToken).where(
                            OauthRefreshToken.token_hash == _sha256(token.token)
                        )
                    )
                ).scalar_one_or_none()
                if row is None or row.revoked_at is not None:
                    return
                user_id, client_id = row.user_id, row.client_id
            kind = "refresh"
        elif isinstance(token, AccessToken):
            async with SessionLocal() as db:
                row = (
                    await db.execute(
                        select(AuthToken).where(AuthToken.token_hash == _sha256(token.token))
                    )
                ).scalar_one_or_none()
                if row is None or row.client_id is None or row.revoked_at is not None:
                    return
                user_id, client_id = row.user_id, row.client_id
            kind = "access"
        else:
            return
        await _revoke_family(user_id, client_id)
        async with SessionLocal() as db:
            await write_audit(
                db,
                event="oauth.token.revoked",
                user_id=user_id,
                target=client_id,
                detail={"kind": kind, "client_id": client_id},
                ip=ip,
                user_agent=ua,
            )
            await db.commit()


# ============ Route mounting ============


class RequestMetaMiddleware:
    """Pure-ASGI middleware publishing request ip/user-agent via the ContextVar
    above — SDK-driven OAuth routes hand no Request object to provider methods,
    so this is the only way audit rows learn where a call came from."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            forwarded = headers.get("x-forwarded-for", "")
            ip = forwarded.split(",")[0].strip() or (scope.get("client") or ("",))[0]
            set_request_meta(ip, headers.get("user-agent", ""))
        await self.app(scope, receive, send)


def mount_oauth_routes(app) -> None:
    """Mount the OAuth 2.1 routes at the app ROOT (well-known discovery lives
    at `/.well-known/*` — a prefix would break it; ADR-0006 covers this for
    the MCP sub-app variant).

    Composition: shadow AS metadata (adds "none" + iss advertising) + SDK auth
    routes (well-known / authorize / token / register / revoke) + PRM routes +
    a bare-path PRM alias (some clients probe the origin directly).

    Degradation: a non-HTTPS, non-loopback issuer makes the SDK factory raise
    — log a warning and mount nothing; the static-token path always works.
    """
    from mcp.server.auth.routes import (
        cors_middleware,
        create_auth_routes,
        create_protected_resource_routes,
    )
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    settings = load_oauth_settings()
    try:
        issuer = http_url(settings.issuer)
        provider = OAuthProvider(settings)
        auth_routes = create_auth_routes(
            provider=provider,
            issuer_url=issuer,
            service_documentation_url=None,
            client_registration_options=registration_options(),
            revocation_options=revocation_options(),
        )
        prm_routes = create_protected_resource_routes(
            resource_url=http_url(settings.resource),
            authorization_servers=[issuer],
            scopes_supported=["mcp"],
            resource_name=get_settings().app_name,
        )
    except ValueError as exc:  # pydantic ValidationError also subclasses ValueError
        logger.warning(
            "OAuth 2.1 not enabled (issuer=%s): %s — static token path unaffected",
            settings.issuer,
            exc,
        )
        return

    extra_routes = []
    sdk_meta_path = next(
        (
            getattr(r, "path", "")
            for r in auth_routes
            if getattr(r, "path", "").startswith("/.well-known/oauth-authorization-server")
        ),
        "",
    )
    if sdk_meta_path:

        async def shadow_metadata(request: Request) -> JSONResponse:
            return JSONResponse(build_as_metadata(settings), headers={"Cache-Control": "no-store"})

        # Starlette matches first route wins: insert before the SDK's own
        # metadata route; every other field renders from the same source.
        extra_routes.append(
            Route(
                sdk_meta_path,
                endpoint=cors_middleware(shadow_metadata, ["GET", "OPTIONS"]),
                methods=["GET", "OPTIONS"],
            )
        )
    else:
        logger.warning(
            "SDK AS metadata route not found; shadow metadata skipped "
            "(auth-methods list will lack 'none')"
        )

    async def prm_alias(request: Request) -> JSONResponse:
        return JSONResponse(build_prm(settings), headers={"Cache-Control": "no-store"})

    extra_routes.append(
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=cors_middleware(prm_alias, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        )
    )

    app.router.routes[:0] = extra_routes + auth_routes + prm_routes
    logger.info("OAuth 2.1 enabled: issuer=%s resource=%s", settings.issuer, settings.resource)
