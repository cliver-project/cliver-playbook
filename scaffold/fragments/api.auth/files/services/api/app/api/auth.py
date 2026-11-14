"""Project-owned registration on top of the playbook auth package."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.auth import RegisterRequest
from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.user.auth.audit import write_audit
from cliver_playbook.app.user.auth.passwords import ahash_password
from cliver_playbook.app.user.auth.tokens import issue_web_token
from cliver_playbook.app.user.models.entities import Role, User, UserRole
from cliver_playbook.app.user.schemas.auth import LoginResponse, UserRead
from cliver_playbook.app.user.services import users as users_service
from cliver_playbook.app.user.services.users import DomainError
from cliver_playbook.app.user.settings import get_settings

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


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded
    return request.client.host if request.client else ""


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Create an account, assign the configured default role and sign in."""
    settings = get_settings()
    role_id = (
        await db.execute(select(Role.id).where(Role.code == settings.registration_role))
    ).scalar_one_or_none()
    if role_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration role is not configured",
        )

    try:
        user = await users_service.create_user(
            db,
            username=payload.username,
            password_hash=await ahash_password(payload.password),
            email=str(payload.email) if payload.email else None,
            display_name=payload.display_name or payload.username,
            role_ids=[role_id],
            must_change_password=False,
        )
    except DomainError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    token = await issue_web_token(
        db,
        user_id=user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    await write_audit(
        db,
        event="auth.register",
        user_id=user.id,
        username=user.username,
        request=request,
    )
    await db.commit()
    return LoginResponse(
        token=token,
        must_change_password=False,
        user=await _user_read(db, user),
    )
