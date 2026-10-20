"""Admin endpoints: user administration, role administration, audit access.

Every endpoint declares `require_perm(...)` — authorization is a property of
the route definition, reviewable by reading this file top to bottom. Audit
rows are written in the same transaction as the mutation they describe.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.user.auth.audit import write_audit
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm
from cliver_playbook.app.user.auth.oauth21 import revoke_grant
from cliver_playbook.app.user.auth.passwords import ahash_password
from cliver_playbook.app.user.auth.permissions import catalog_as_dicts
from cliver_playbook.app.user.auth.tokens import revoke_all_for_user
from cliver_playbook.app.user.models.entities import (
    AuditLog,
    OauthClient,
    OauthRefreshToken,
    RolePermission,
    User,
)
from cliver_playbook.app.user.schemas.auth import (
    AuditLogPage,
    AuditLogRead,
    OauthClientRead,
    OauthGrantRead,
    OauthGrantRevokeRequest,
    PermissionRead,
    ResetPasswordRequest,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)
from cliver_playbook.app.user.services import roles as roles_service
from cliver_playbook.app.user.services import users as users_service
from cliver_playbook.app.user.services.users import DomainError
from cliver_playbook.app.user.timeutil import utcnow

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _domain_error(exc: DomainError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------


@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    _viewer: Viewer = Depends(require_perm("role:read")),
) -> list[dict]:
    """The code-defined catalog — the pick-list for role permission binding."""
    return catalog_as_dicts()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _user_read(user, role_codes: list[str], permission_codes: list[str]) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        phone=user.phone,
        display_name=user.display_name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        role_codes=sorted(role_codes),
        permissions=sorted(permission_codes),
    )


@router.get("/users", response_model=list[UserRead])
async def list_users(
    q: str | None = Query(default=None, max_length=64),
    _viewer: Viewer = Depends(require_perm("user:read")),
    db: AsyncSession = Depends(get_db),
) -> list[UserRead]:
    rows = await users_service.list_users(db, q=q)
    return [_user_read(row["user"], row["role_codes"], row["permission_codes"]) for row in rows]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    request: Request,
    viewer: Viewer = Depends(require_perm("user:create")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    role_ids = await roles_service.validate_role_ids(db, payload.role_ids)
    try:
        user = await users_service.create_user(
            db,
            username=payload.username,
            password_hash=await ahash_password(payload.password),
            email=payload.email,
            phone=payload.phone,
            display_name=payload.display_name,
            role_ids=role_ids,
            must_change_password=payload.must_change_password,
            granted_by=viewer.user_id,
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    await write_audit(
        db,
        event="admin.user.create",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"user:{user.id}:{user.username}",
        detail={"role_ids": role_ids},
        request=request,
    )
    await db.commit()
    roles = await users_service._role_codes_for_user(db, user.id)
    perms = await users_service.permission_codes_for_user(db, user.id)
    return _user_read(user, sorted(roles), sorted(perms))


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    _viewer: Viewer = Depends(require_perm("user:read")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await users_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    roles = await users_service._role_codes_for_user(db, user.id)
    perms = await users_service.permission_codes_for_user(db, user.id)
    return _user_read(user, sorted(roles), sorted(perms))


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    viewer: Viewer = Depends(require_perm("user:update")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await users_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Only fields actually PRESENT in the request body are forwarded: the
    # service treats _UNSET as "leave unchanged" and explicit None as
    # "clear" — conflating the two would make clearing email/phone
    # impossible (pydantic maps absent and null to the same Python None).
    updates: dict = {}
    for field in ("email", "phone", "display_name", "is_active"):
        if field in payload.model_fields_set:
            updates[field] = getattr(payload, field)
    role_ids = None
    if "role_ids" in payload.model_fields_set:
        role_ids = await roles_service.validate_role_ids(db, payload.role_ids or [])
        updates["role_ids"] = role_ids
    try:
        await users_service.update_user(db, user, actor_id=viewer.user_id, **updates)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    await write_audit(
        db,
        event="admin.user.update",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"user:{user_id}:{user.username}",
        detail={
            "is_active": payload.is_active,
            "role_ids": role_ids,
        },
        request=request,
    )
    await db.commit()
    roles = await users_service._role_codes_for_user(db, user.id)
    perms = await users_service.permission_codes_for_user(db, user.id)
    return _user_read(user, sorted(roles), sorted(perms))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    viewer: Viewer = Depends(require_perm("user:delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await users_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        await users_service.delete_user(db, user, actor_id=viewer.user_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    await write_audit(
        db,
        event="admin.user.delete",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"user:{user_id}:{user.username}",
        request=request,
    )
    await db.commit()


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    viewer: Viewer = Depends(require_perm("user:reset_password")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin-forced password reset: target must change it at next login; all
    the target's tokens (sessions, static, OAuth access) are revoked now."""
    user = await users_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    await users_service.admin_reset_password(db, user, await ahash_password(payload.new_password))
    await write_audit(
        db,
        event="admin.user.reset_password",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"user:{user_id}:{user.username}",
        request=request,
    )
    await db.commit()
    return {"ok": True, "must_change_password": True}


@router.post("/users/{user_id}/force-logout")
async def force_logout(
    user_id: int,
    request: Request,
    viewer: Viewer = Depends(require_perm("user:force_logout")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await users_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    revoked = await revoke_all_for_user(db, user.id)
    await write_audit(
        db,
        event="admin.user.force_logout",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"user:{user_id}:{user.username}",
        detail={"revoked_tokens": revoked},
        request=request,
    )
    await db.commit()
    return {"ok": True, "revoked_tokens": revoked}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


async def _role_permission_codes(db: AsyncSession, role_id: int) -> list[str]:
    return sorted(
        code
        for (code,) in await db.execute(
            select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
        )
    )


def _role_read(role, permission_codes: list[str]) -> RoleRead:
    return RoleRead(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        created_at=role.created_at,
        permission_codes=sorted(permission_codes),
    )


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    _viewer: Viewer = Depends(require_perm("role:read")),
    db: AsyncSession = Depends(get_db),
) -> list[RoleRead]:
    rows = await roles_service.list_roles(db)
    return [_role_read(row["role"], row["permission_codes"]) for row in rows]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    request: Request,
    viewer: Viewer = Depends(require_perm("role:manage")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    try:
        role = await roles_service.create_role(
            db,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            permission_codes=payload.permission_codes,
            actor=viewer,
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    await write_audit(
        db,
        event="admin.role.create",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"role:{role.id}:{role.code}",
        detail={"permission_codes": payload.permission_codes},
        request=request,
    )
    await db.commit()
    return _role_read(role, await _role_permission_codes(db, role.id))


@router.patch("/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    request: Request,
    viewer: Viewer = Depends(require_perm("role:manage")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await roles_service.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    try:
        await roles_service.update_role(
            db,
            role,
            name=payload.name,
            description=payload.description,
            code=payload.code,
            permission_codes=payload.permission_codes,
            actor=viewer,
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    await write_audit(
        db,
        event="admin.role.update",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"role:{role_id}:{role.code}",
        detail={"permission_codes": payload.permission_codes or []},
        request=request,
    )
    await db.commit()
    return _role_read(role, await _role_permission_codes(db, role.id))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    request: Request,
    viewer: Viewer = Depends(require_perm("role:manage")),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await roles_service.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    try:
        await roles_service.delete_role(db, role, actor=viewer)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    await write_audit(
        db,
        event="admin.role.delete",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"role:{role_id}:{role.code}",
        request=request,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# OAuth provider administration (ADR-0005)
# ---------------------------------------------------------------------------


@router.get("/oauth/clients", response_model=list[OauthClientRead])
async def list_oauth_clients(
    _viewer: Viewer = Depends(require_perm("oauth:read")),
    db: AsyncSession = Depends(get_db),
) -> list[OauthClientRead]:
    """Clients registered via DCR. Registration is open by design (agents
    self-register before their first authorize), so this listing is the
    operator's only visibility into who has ever connected."""
    rows = (
        (await db.execute(select(OauthClient).order_by(OauthClient.created_at.desc())))
        .scalars()
        .all()
    )
    out = []
    for row in rows:
        meta = row.client_metadata or {}
        out.append(
            OauthClientRead(
                client_id=row.client_id,
                client_name=row.client_name,
                redirect_uris=[str(u) for u in (meta.get("redirect_uris") or [])],
                grant_types=[str(g) for g in (meta.get("grant_types") or [])],
                created_at=row.created_at,
            )
        )
    return out


@router.get("/oauth/grants", response_model=list[OauthGrantRead])
async def list_oauth_grants(
    _viewer: Viewer = Depends(require_perm("oauth:read")),
    db: AsyncSession = Depends(get_db),
) -> list[OauthGrantRead]:
    """Live grants = unrevoked, unexpired refresh-token chains. This is the
    answer to 'which agents can act as which user right now'."""
    stmt = (
        select(OauthRefreshToken, User.username, OauthClient.client_name)
        .join(User, User.id == OauthRefreshToken.user_id)
        .outerjoin(OauthClient, OauthClient.client_id == OauthRefreshToken.client_id)
        .where(
            OauthRefreshToken.revoked_at.is_(None),
            OauthRefreshToken.expires_at > utcnow(),
        )
        .order_by(OauthRefreshToken.created_at.desc())
    )
    return [
        OauthGrantRead(
            id=row.id,
            user_id=row.user_id,
            username=username,
            client_id=row.client_id,
            # A client row deleted out-of-band must not blank the grant list.
            client_name=client_name or row.client_id,
            scopes=[s for s in row.scopes.split(" ") if s],
            granted_at=row.created_at,
            expires_at=row.expires_at,
        )
        for row, username, client_name in await db.execute(stmt)
    ]


@router.post("/oauth/grants/revoke")
async def revoke_oauth_grant(
    payload: OauthGrantRevokeRequest,
    request: Request,
    viewer: Viewer = Depends(require_perm("oauth:revoke")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke every live grant for a (user, client) pair — refresh chains AND
    OAuth access tokens, so the agent's current requests die too. Idempotent:
    revoking an already-dead pair reports zero and stays a success."""
    revoked = await revoke_grant(db, user_id=payload.user_id, client_id=payload.client_id)
    await write_audit(
        db,
        event="admin.oauth.revoke_grant",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"oauth:{payload.client_id}:user:{payload.user_id}"[:128],
        detail={"revoked_refresh_tokens": revoked},
        request=request,
    )
    await db.commit()
    return {"ok": True, "revoked_refresh_tokens": revoked}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@router.get("/audit", response_model=AuditLogPage)
async def list_audit(
    event: str | None = Query(default=None, max_length=64),
    username: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _viewer: Viewer = Depends(require_perm("audit:read")),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    count_stmt = select(func.count()).select_from(AuditLog)
    if event:
        stmt = stmt.where(AuditLog.event == event)
        count_stmt = count_stmt.where(AuditLog.event == event)
    if username:
        stmt = stmt.where(AuditLog.username.ilike(f"%{username}%"))
        count_stmt = count_stmt.where(AuditLog.username.ilike(f"%{username}%"))
    rows = await db.execute(stmt.limit(limit).offset(offset))
    total = await db.scalar(count_stmt)
    return AuditLogPage(
        items=[AuditLogRead.model_validate(row) for row in rows.scalars().all()],
        total=int(total or 0),
    )
