"""Router registry for the governance package.

Each workflow area owns a module and contributes one router here; the
package's ``app.create_app`` and any composed application include the
same list. Keeping the health route in this module means the registry
is importable before the database models exist, which the package
skeleton's boot test relies on.
"""

from __future__ import annotations

from fastapi import APIRouter

from cliver_playbook.app.rag_governance.api.batches import router as batches_router
from cliver_playbook.app.rag_governance.api.evaluations import router as evaluations_router
from cliver_playbook.app.rag_governance.api.golden import router as golden_router
from cliver_playbook.app.rag_governance.api.projects import router as projects_router
from cliver_playbook.app.rag_governance.api.rules import router as rules_router
from cliver_playbook.app.rag_governance.api.sources import router as sources_router

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe that does not touch the database."""
    return {"status": "ok"}


ROUTERS: list[APIRouter] = [
    router,
    projects_router,
    sources_router,
    batches_router,
    golden_router,
    rules_router,
    evaluations_router,
]
