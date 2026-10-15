"""Meta endpoints: liveness with a real database ping, and version info."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(prefix=settings.api_v1_prefix, tags=["meta"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """Liveness probe — verifies the process AND a real database round-trip."""
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict:
    return {"app": settings.app_name, "api": "v1"}
