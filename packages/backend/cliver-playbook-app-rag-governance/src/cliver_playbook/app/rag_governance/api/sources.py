"""Source endpoints and the ingest trigger.

Triggering ingest is asynchronous: the request creates a queued batch,
enqueues one durable job, and returns 202. The job claim is the only
place work starts, so a crashed API process never leaves a half-run
batch and two API calls cannot run the same ingest twice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.runtime import enqueue
from cliver_playbook.app.rag_governance.schemas.sources import (
    IngestAccepted,
    IngestRequest,
    SourceCreate,
    SourceList,
    SourceRead,
)
from cliver_playbook.app.rag_governance.services import batches as batch_service
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.rag_governance.services import sources as source_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_PROJECT_READ = Security(require_perm("rag_governance:project:read"))
_SOURCE_WRITE = Security(require_perm("rag_governance:source:write"))


@router.post(
    "/projects/{project_id}/sources",
    status_code=201,
    response_model=SourceRead,
)
async def create_source(
    project_id: str,
    payload: SourceCreate,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _SOURCE_WRITE,
) -> SourceRead:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        source = await source_service.create_source(
            db,
            project,
            kind=payload.kind,
            config=payload.config,
            authority=payload.authority,
            sync_schedule=payload.sync_schedule,
            sync_enabled=payload.sync_enabled,
            max_staleness_seconds=payload.max_staleness_seconds,
        )
    except source_service.SourceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return SourceRead.from_row(source)


@router.get("/projects/{project_id}/sources", response_model=SourceList)
async def list_sources(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _PROJECT_READ,
) -> SourceList:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    sources = await source_service.list_sources(db, project_id)
    return SourceList(items=[SourceRead.from_row(source) for source in sources])


@router.post(
    "/sources/{source_id}/ingest",
    status_code=202,
    response_model=IngestAccepted,
)
async def trigger_ingest(
    source_id: str,
    _payload: IngestRequest,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _SOURCE_WRITE,
) -> IngestAccepted:
    source = await source_service.get_source(db, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    project = await project_service.get_project(db, source.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="project is archived")
    if source.authority == "capability":
        # A capability source describes how to query the ERP, not
        # content to embed. Ingesting it would put a tool manual into
        # the knowledge base.
        raise HTTPException(
            status_code=422,
            detail="capability sources are queried live and are not ingested",
        )

    try:
        batch = await batch_service.create_batch(db, project, source, submitted_by=viewer.username)
    except batch_service.BatchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    job = await enqueue(
        db,
        project_id=project.id,
        kind="ingest_batch",
        payload={"batch_id": batch.id, "source_id": source.id},
        # One job per batch: a retried HTTP request or a duplicated
        # sync tick collapses into the same unit of work.
        dedupe_key=f"ingest_batch:{batch.id}",
    )
    await db.commit()
    return IngestAccepted(
        batch_id=batch.id,
        job_id=job.id,
        kind=job.kind,
        status=job.status,
    )
