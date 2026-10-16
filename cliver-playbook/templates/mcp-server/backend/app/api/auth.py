"""Authentication endpoints: session login/logout, profile, password change,
OIDC login, and self-service linking/unlinking of external identities
(OIDC mechanics delegated to app.auth.oidc).

Transaction discipline: unlike the scaffold's demo items (whose service
commits), identity routers use one commit per request at the END — service
mutations and their audit rows commit atomically. A failed login is the one
place that commits BEFORE raising, so the failure audit survives the 401.
"""

import hashlib
import secrets
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import write_audit
from app.auth.dependencies import Viewer, get_current_user
from app.auth.oauth21 import (
    build_authorization_redirect,
    client_display_name,
    issue_authorization_code,
    load_oauth_settings,
    verify_login_blob,
)
from app.auth.oidc import (
    build_authorize_url,
    build_provider_registry,
    endpoints_for,
    exchange_code,
    fetch_userinfo,
    find_linked_user,
    make_pkce_pair,
    sign_state_blob,
    state_cookie_name,
    verify_state_blob,
)
from app.auth.passwords import ahash_password, averify_password, needs_rehash
from app.auth.tokens import issue_web_token, revoke_all_for_user, revoke_token_by_id
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import OauthIdentity, Role, User, UserRole
from app.schemas.auth import (
    ChangePasswordRequest,
    IdentityLinkStart,
    LinkedIdentityRead,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OAuthAuthorizeRequest,
    ProfileUpdate,
    UserRead,
)
from app.services import users as users_service
from app.services.users import DomainError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _user_read(db: AsyncSession, user: User) -> UserRead:
    role_codes = sorted(
        code
        for (code,) in await db.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
    )
    permissions = sorted(await users_service.permission_codes_for_user(db, user.id))
    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        phone=user.phone,
        display_name=user.display_name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        role_codes=role_codes,
        permissions=permissions,
    )


# ---------------------------------------------------------------------------
# Password session
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    result = await users_service.authenticate(db, payload.username, payload.password)
    if not result.ok or result.user is None:
        # Commit the failure audit before raising — the 401 must not roll it back.
        await write_audit(
            db,
            event="auth.login",
            username=payload.username[:100],
            ok=False,
            error=result.reason or "invalid",
            request=request,
        )
        await db.commit()
        if result.reason == "locked":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked. Try again later.",
            )
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user = result.user
    token = await issue_web_token(
        db,
        user_id=user.id,
        ip=request.headers.get("x-forwarded-for", request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", ""),
    )
    # Transparent re-hash upgrade: stored hash predates current iterations.
    if needs_rehash(user.password_hash):
        user.password_hash = await ahash_password(payload.password)
    await write_audit(
        db, event="auth.login", user_id=user.id, username=user.username, request=request
    )
    await db.commit()
    return LoginResponse(
        token=token,
        must_change_password=user.must_change_password,
        user=await _user_read(db, user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    viewer: Viewer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke the presented token (this device/session only)."""
    if viewer.token_id is not None:
        await revoke_token_by_id(db, viewer.token_id)
    await write_audit(
        db, event="auth.logout", user_id=viewer.user_id, username=viewer.username, request=request
    )
    await db.commit()


@router.get("/me", response_model=MeResponse)
async def me(
    viewer: Viewer = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MeResponse:
    user = await users_service.get_user(db, viewer.user_id)
    if user is None:  # raced with deletion mid-request
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return MeResponse(user=await _user_read(db, user))


@router.post("/change-password", response_model=LoginResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    viewer: Viewer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Self-service password change.

    Reachable while the must-change-password gate is active (it is the whole
    point of the gate). Revokes every token everywhere, then re-issues one
    fresh web token so this browser stays signed in; every other session
    (including MCP static tokens) is dropped.
    """
    user = await users_service.get_user(db, viewer.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not await averify_password(payload.old_password, user.password_hash):
        await write_audit(
            db,
            event="auth.change_password",
            user_id=user.id,
            username=user.username,
            ok=False,
            error="wrong current password",
            request=request,
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    await users_service.set_password(db, user, await ahash_password(payload.new_password))
    await revoke_all_for_user(db, user.id)
    token = await issue_web_token(
        db,
        user_id=user.id,
        ip=request.headers.get("x-forwarded-for", request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", ""),
    )
    await write_audit(
        db, event="auth.change_password", user_id=user.id, username=user.username, request=request
    )
    await db.commit()
    return LoginResponse(
        token=token,
        must_change_password=False,
        user=await _user_read(db, user),
    )


@router.patch("/profile", response_model=MeResponse)
async def update_profile(
    payload: ProfileUpdate,
    request: Request,
    viewer: Viewer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Self-service profile edit: display name, email, phone.

    Deliberately narrow — no username (stable identity), no roles, no
    activation; those stay admin-only (see ProfileUpdate). Password changes
    are their own endpoint because they revoke tokens. Any authenticated
    user may call this, including one behind the must-change-password gate
    (fixing contact details should not be blocked by it).
    """
    user = await users_service.get_user(db, viewer.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # Forward only fields PRESENT in the body: the service distinguishes
    # "absent" (unchanged) from explicit null/"" (clear) — see _UNSET.
    updates: dict = {
        field: getattr(payload, field)
        for field in ("email", "phone", "display_name")
        if field in payload.model_fields_set
    }
    try:
        await users_service.update_own_profile(db, user, **updates)
    except DomainError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await write_audit(
        db,
        event="auth.profile_update",
        user_id=user.id,
        username=user.username,
        target=f"user:{user.id}:{user.username}",
        detail={"fields": sorted(updates)},
        request=request,
    )
    await db.commit()
    return MeResponse(user=await _user_read(db, user))


# ---------------------------------------------------------------------------
# OIDC login
# ---------------------------------------------------------------------------


@router.get("/oauth/providers")
async def oauth_providers() -> dict:
    """Which SSO providers the login page should render buttons for.

    The label comes from configuration; an unset label falls back to the
    provider key in title case so the button is never blank.
    """
    registry = build_provider_registry()
    return {
        "providers": [
            {"key": key, "label": config.label or key.title()} for key, config in registry.items()
        ]
    }


def _redirect_uri(request: Request, provider_key: str) -> str:
    settings = get_settings()
    base = (
        settings.oidc.redirect_base.rstrip("/")
        if settings.oidc.redirect_base
        else str(request.base_url).rstrip("/")
    )
    return f"{base}/api/v1/auth/oauth/{provider_key}/callback"


@router.get("/oauth/{provider}/login")
async def oauth_login(provider: str, request: Request) -> RedirectResponse:
    registry = build_provider_registry()
    config = registry.get(provider)
    if config is None:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")

    state = secrets.token_hex(16)
    verifier, challenge = make_pkce_pair()
    try:
        document = await endpoints_for(config)
    except (httpx.HTTPError, ValueError):
        # Unreachable or malformed IdP (discovery is the only outbound call
        # here) is a runtime condition, not a server bug: land on the SPA's
        # error page like any other login failure instead of a bare 500.
        # ValueError covers malformed JSON from the IdP.
        frontend = get_settings().web_base_url.rstrip("/")
        return RedirectResponse(
            f"{frontend}/auth/callback#{urlencode({'error': 'idp_error'})}",
            status_code=status.HTTP_302_FOUND,
        )
    url = build_authorize_url(
        config,
        document,
        state=state,
        code_challenge=challenge,
        redirect_uri=_redirect_uri(request, provider),
    )
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        state_cookie_name,
        sign_state_blob(provider, state, verifier),
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Complete OIDC login and hand the session token to the SPA.

    Success: 302 `{web_base_url}/auth/callback#token=...` — the token rides in
    the URL fragment, which browsers never send to any server (no logs, no
    Referer leak). Failure: same page with `#error=...`.
    """
    settings = get_settings()
    frontend = settings.web_base_url.rstrip("/")
    registry = build_provider_registry()
    config = registry.get(provider)

    def _fail(reason: str) -> RedirectResponse:
        target = f"{frontend}/auth/callback#{urlencode({'error': reason})}"
        redirect = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
        redirect.delete_cookie(state_cookie_name)
        return redirect

    if config is None:
        return _fail("unknown_provider")
    if error or not code:
        return _fail(error or "missing_code")

    blob = request.cookies.get(state_cookie_name, "")
    data = verify_state_blob(blob, provider_key=provider, state=state)
    if data is None:
        await write_audit(
            db,
            event="auth.oauth.callback",
            ok=False,
            error="state mismatch or expired",
            request=request,
        )
        await db.commit()
        return _fail("state_mismatch")
    verifier = str(data["verifier"])

    try:
        document = await endpoints_for(config)
        token_response = await exchange_code(
            config,
            document,
            code=code,
            code_verifier=verifier,
            redirect_uri=_redirect_uri(request, provider),
        )
        if not isinstance(token_response, dict):
            raise TypeError("token response is not a JSON object")
        access_token = str(token_response.get("access_token", "") or "")
        userinfo = await fetch_userinfo(document, access_token)
        if not isinstance(userinfo, dict):
            raise TypeError("userinfo response is not a JSON object")
    except (httpx.HTTPError, ValueError, TypeError):
        # IdP unreachable, error status (raise_for_status -> HTTPStatusError,
        # an HTTPError subclass), nonsense payload (resp.json() ->
        # JSONDecodeError, a ValueError subclass) or wrong payload shape
        # (TypeError above). Runtime condition -> audited SPA error
        # redirect, never a bare 500.
        await write_audit(
            db,
            event="auth.oauth.callback",
            ok=False,
            error="idp_error",
            request=request,
        )
        await db.commit()
        return _fail("idp_error")

    # The stable provider-side user id lives in a configurable claim: "sub"
    # for standard OIDC, "id" (numeric, stringified here) for GitHub-style
    # APIs. `or ""` coerces null claims; [:255] matches the column width.
    subject = str(userinfo.get(config.subject_claim, "") or "")[:255]
    if not subject:
        return _fail("no_subject")

    # Account-linking flow (started from the profile page): attach the now-
    # verified identity to the user pinned in the signed state. Never issues
    # a session token — the user already has one; that is the whole point.
    if data.get("mode") == "link":
        link_user_id = data.get("user_id")
        if not isinstance(link_user_id, int) or isinstance(link_user_id, bool) or link_user_id <= 0:
            # A link blob without a valid pinned user id is corrupt.
            return _fail("state_mismatch")
        return await _complete_identity_link(
            db,
            request=request,
            provider=provider,
            userinfo=userinfo,
            subject=subject,
            user_id=link_user_id,
            frontend=frontend,
        )

    user_id = await find_linked_user(db, provider, subject)
    if user_id is None:
        if not config.auto_provision:
            await write_audit(
                db,
                event="auth.oauth.callback",
                username=str(userinfo.get("email", ""))[:100],
                ok=False,
                error="identity not linked and auto-provision disabled",
                request=request,
            )
            await db.commit()
            return _fail("not_allowed")
        user_id = await _provision_user(db, config, provider, userinfo)

    user = await users_service.get_user(db, user_id)
    if user is None or not user.is_active:
        return _fail("not_allowed")

    token = await issue_web_token(
        db,
        user_id=user.id,
        ip=request.headers.get("x-forwarded-for", request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", ""),
    )
    await write_audit(
        db,
        event="auth.oauth.login",
        user_id=user.id,
        username=user.username,
        target=f"oidc:{provider}",
        request=request,
    )
    await db.commit()

    target = f"{frontend}/auth/callback#{urlencode({'token': token, 'must_change_password': str(user.must_change_password).lower()})}"
    redirect = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(state_cookie_name)
    return redirect


async def _provision_user(db: AsyncSession, config, provider_key: str, userinfo: dict) -> int:
    """Create a local account + identity link for a first-time SSO user."""
    # Same claim mapping as the callback's identity lookup — the subject
    # stored here must byte-match what the next login will look up.
    subject = str(userinfo.get(config.subject_claim, "") or "")[:255]
    email = str(userinfo.get("email", "") or "")
    display_name = str(
        userinfo.get("name") or userinfo.get("preferred_username") or email or subject[:32]
    )[:128]
    # Deterministic, collision-tolerant username from the identity itself.
    base = email.split("@")[0][:32] if email else f"{provider_key}_{subject[:16]}"
    digest = hashlib.sha256(f"{provider_key}:{subject}".encode()).hexdigest()[:6]
    username = f"{base}_{digest}"[:64]

    role_id = (
        await db.execute(select(Role.id).where(Role.code == config.default_role))
    ).scalar_one_or_none()

    # Standard OIDC contact claim; most IdPs omit it, so "" → None is normal.
    phone = str(userinfo.get("phone_number", "") or "")[:32]

    user = User(
        username=username,
        email=email or None,
        phone=phone or None,
        password_hash="",  # OIDC-only account: no local password
        display_name=display_name,
    )
    db.add(user)
    await db.flush()
    if role_id is not None:
        db.add(UserRole(user_id=user.id, role_id=role_id))
    db.add(
        OauthIdentity(
            provider=provider_key,
            subject=subject,
            user_id=user.id,
            email=email[:255],
            display_name=display_name[:128],
        )
    )
    await db.flush()
    return user.id


# ---------------------------------------------------------------------------
# Linked external identities (profile page self-service)
# ---------------------------------------------------------------------------


@router.get("/identities", response_model=list[LinkedIdentityRead])
async def list_identities(
    viewer: Viewer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LinkedIdentityRead]:
    """The viewer's linked external identities ("Linked accounts" card).

    provider_label resolves through the FULL settings registry — disabled
    presets included — so a provider switched off after linking still shows a
    sane name; an identity whose key vanished from the config falls back to
    the raw key. is_last_credential flags the one row an OIDC-only account
    cannot unlink (the DELETE enforces it with 409 regardless).
    """
    user = await users_service.get_user(db, viewer.user_id)
    if user is None:  # raced with deletion mid-request
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    rows = (
        (
            await db.execute(
                select(OauthIdentity)
                .where(OauthIdentity.user_id == viewer.user_id)
                .order_by(OauthIdentity.linked_at, OauthIdentity.id)
            )
        )
        .scalars()
        .all()
    )
    labels = {
        key: (provider.label or key.title())
        for key, provider in get_settings().oidc.providers.items()
    }
    oidc_only = user.password_hash == ""
    return [
        LinkedIdentityRead(
            id=row.id,
            provider=row.provider,
            provider_label=labels.get(row.provider, row.provider),
            email=row.email,
            display_name=row.display_name,
            linked_at=row.linked_at,
            # Only meaningful for an OIDC-only account down to its last row:
            # a password account always has its password to fall back on.
            is_last_credential=oidc_only and len(rows) == 1,
        )
        for row in rows
    ]


@router.post("/identities/{provider}/link")
async def start_identity_link(
    provider: str,
    request: Request,
    viewer: Viewer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Begin linking an external identity to the signed-in account.

    Same authorize redirect + state cookie as a login, but the signed blob
    carries mode="link" plus the viewer's user id, so the callback attaches
    the identity instead of issuing a session. Returns the IdP authorize URL
    for the SPA to navigate to — a full-page navigation, since the redirect
    chain must leave the SPA. IdP unavailability surfaces as a 502: this is
    a direct API call (no redirect target to steer), so a plain error
    response is the honest signal.
    """
    registry = build_provider_registry()
    config = registry.get(provider)
    if config is None:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")

    state = secrets.token_hex(16)
    verifier, challenge = make_pkce_pair()
    try:
        document = await endpoints_for(config)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="Identity provider is unavailable")
    url = build_authorize_url(
        config,
        document,
        state=state,
        code_challenge=challenge,
        # Same callback URL as a login: the IdP sees one registered redirect
        # URI per provider, the mode lives in the signed cookie, not the URL.
        redirect_uri=_redirect_uri(request, provider),
    )
    response = JSONResponse(content=IdentityLinkStart(redirect_url=url).model_dump())
    response.set_cookie(
        state_cookie_name,
        sign_state_blob(provider, state, verifier, mode="link", user_id=viewer.user_id),
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.delete("/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_identity(
    identity_id: int,
    request: Request,
    viewer: Viewer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove one of the viewer's linked external identities.

    A missing OR foreign identity is a plain 404 — no existence leak across
    users. The last credential of an OIDC-only account (password_hash='')
    is protected server-side with 409: greying the button out in the UI is
    courtesy, this is the enforcement. A password account may unlink all
    its identities; the password remains the fallback credential.
    """
    identity = (
        await db.execute(select(OauthIdentity).where(OauthIdentity.id == identity_id))
    ).scalar_one_or_none()
    if identity is None or identity.user_id != viewer.user_id:
        raise HTTPException(status_code=404, detail="Identity not found")

    user = await users_service.get_user(db, viewer.user_id)
    if user is None:  # raced with deletion mid-request
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user.password_hash == "":
        remaining = await db.scalar(
            select(func.count())
            .select_from(OauthIdentity)
            .where(OauthIdentity.user_id == viewer.user_id)
        )
        if (remaining or 0) <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot remove the last remaining credential of an account "
                    "without a password; set a password first"
                ),
            )
    await db.delete(identity)
    await write_audit(
        db,
        event="auth.identity.unlink",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"oidc:{identity.provider}",
        request=request,
    )
    await db.commit()


async def _complete_identity_link(
    db: AsyncSession,
    *,
    request: Request,
    provider: str,
    userinfo: dict,
    subject: str,
    user_id: int,
    frontend: str,
) -> RedirectResponse:
    """Attach a freshly-verified IdP identity to the pinned local account.

    The user was authenticated by their session token at link START and the
    signed blob pinned that user id; the callback only re-checks liveness.
    Outcomes land on the profile page as URL fragments (#linked=provider /
    #link_error=reason) for the SPA to toast — never a #token= fragment.
    """

    def _done(fragment: str) -> RedirectResponse:
        redirect = RedirectResponse(
            f"{frontend}/profile#{fragment}", status_code=status.HTTP_302_FOUND
        )
        redirect.delete_cookie(state_cookie_name)
        return redirect

    user = await users_service.get_user(db, user_id)
    if user is None or not user.is_active:
        return _done("link_error=not_allowed")
    # Captured before any INSERT: a rollback below expires every instance in
    # the session, and touching an expired attribute from sync audit code
    # would trigger a lazy refresh outside async context.
    username = user.username

    existing_user_id = await find_linked_user(db, provider, subject)
    if existing_user_id == user.id:
        return _done(f"linked={quote(provider)}")  # idempotent re-link
    if existing_user_id is not None:
        # The IdP identity already belongs to another local account — the
        # user should log in with it instead of attaching it here.
        await write_audit(
            db,
            event="auth.identity.link",
            user_id=user_id,
            username=username,
            target=f"oidc:{provider}",
            ok=False,
            error="already_linked",
            request=request,
        )
        await db.commit()
        return _done("link_error=already_linked")

    # Snapshot columns (same shape as login-time provisioning), truncated to
    # their column widths; nullable IdP emails coerce to "".
    email = str(userinfo.get("email", "") or "")[:255]
    display_name = str(
        userinfo.get("name") or userinfo.get("preferred_username") or email or subject[:32]
    )[:128]
    db.add(
        OauthIdentity(
            provider=provider,
            subject=subject,
            user_id=user.id,
            email=email,
            display_name=display_name,
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        # Lost a race against a concurrent link/login of the same (provider,
        # subject): the unique constraint tripped after our check above.
        # Same user-visible outcome as the check — and the rollback keeps the
        # failed insert from poisoning the audit write that follows.
        await db.rollback()
        await write_audit(
            db,
            event="auth.identity.link",
            user_id=user_id,
            username=username,
            target=f"oidc:{provider}",
            ok=False,
            error="already_linked (race)",
            request=request,
        )
        await db.commit()
        return _done("link_error=already_linked")
    await write_audit(
        db,
        event="auth.identity.link",
        user_id=user.id,
        username=user.username,
        target=f"oidc:{provider}",
        request=request,
    )
    await db.commit()
    return _done(f"linked={quote(provider)}")


# ---------------------------------------------------------------------------
# OAuth 2.1 authorize hand-off (the SPA authorize page's backend)
# ---------------------------------------------------------------------------


@router.get("/oauth/authorize/info")
async def oauth_authorize_info(blob: str) -> dict:
    """What the authorize page should display: client name + scopes.

    Leaks nothing sensitive — the blob is signed by us and its contents
    (client id, scopes) are shown to the user precisely so they can make an
    informed consent.
    """
    data = verify_login_blob(blob)
    if data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization request")
    client_name = await client_display_name(str(data.get("cid") or ""))
    return {
        "client_name": client_name or "Unknown client",
        "scopes": data.get("sc") or [],
    }


@router.post("/oauth/authorize")
async def oauth_authorize_submit(
    payload: OAuthAuthorizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Complete an agent's authorization: verify blob, authenticate the user,
    store the authorization code, and return the redirect URL the SPA must
    navigate to (it carries code + state + iss back to the agent's callback).

    Scopes/challenge/redirect come exclusively from the VERIFIED blob — form
    input cannot tamper with them. Login lockout applies exactly as elsewhere.
    """
    data = verify_login_blob(payload.blob)
    if data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization request")

    oauth_settings = load_oauth_settings()
    result = await users_service.authenticate(db, payload.username, payload.password)
    if not result.ok or result.user is None:
        await write_audit(
            db,
            event="oauth.authorize",
            username=payload.username[:100],
            target=str(data.get("cid") or "")[:128],
            ok=False,
            error=result.reason or "invalid",
            request=request,
        )
        await db.commit()
        if result.reason == "locked":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked. Try again later.",
            )
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user = result.user
    if user.must_change_password:
        await write_audit(
            db,
            event="oauth.authorize",
            user_id=user.id,
            username=user.username,
            target=str(data.get("cid") or "")[:128],
            ok=False,
            error="must_change_password",
            request=request,
        )
        await db.commit()
        raise HTTPException(status_code=403, detail={"code": "must_change_password"})

    code = await issue_authorization_code(oauth_settings, data, user_id=user.id)
    if code is None:
        raise HTTPException(status_code=400, detail="Unknown OAuth client")
    redirect_url = build_authorization_redirect(oauth_settings, data, code)
    await write_audit(
        db,
        event="oauth.authorize",
        user_id=user.id,
        username=user.username,
        target=str(data.get("cid") or "")[:128],
        request=request,
    )
    await db.commit()
    return {"redirect_url": redirect_url}
