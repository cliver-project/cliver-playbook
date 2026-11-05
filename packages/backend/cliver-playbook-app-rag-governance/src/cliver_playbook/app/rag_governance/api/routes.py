"""Router registry for the governance package.

Each workflow area owns a module and contributes one router here; the
package's ``app.create_app`` and any composed application include the
same list. Keeping the health route in this module means the registry
is importable before the database models exist, which the package
skeleton's boot test relies on.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe that does not touch the database."""
    return {"status": "ok"}


ROUTERS: list[APIRouter] = [router]
