"""Meta endpoints: liveness with a real database ping, and version info."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.basic.settings import settings

# Static prefix: the API version is part of the URL surface, so it lives in
# the route table (greppable), not in settings — a router is built at import
# time and must not depend on which Settings instance happens to load first
# (see the note in settings.py).
router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """Liveness probe — verifies the process AND a real database round-trip."""
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict:
    """Report the application name (resolved per request through the settings proxy)."""
    return {"app": settings.app_name, "api": "v1"}
