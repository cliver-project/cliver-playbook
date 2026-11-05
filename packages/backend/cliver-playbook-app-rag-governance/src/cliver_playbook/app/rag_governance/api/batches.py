"""Batch endpoints and the permission-gated staged preview."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.schemas.batches import (
    BatchList,
    BatchRead,
    StagedDocumentList,
    StagedDocumentRead,
)
from cliver_playbook.app.rag_governance.services import batches as batch_service
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_PROJECT_READ = Security(require_perm("rag_governance:project:read"))
_JOB_READ = Security(require_perm("rag_governance:job:read"))
_STAGED_READ = Security(require_perm("rag_governance:staged:read"))


@router.get("/projects/{project_id}/batches", response_model=BatchList)
async def list_batches(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _PROJECT_READ,
) -> BatchList:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    batches = await batch_service.list_batches(db, project_id)
    return BatchList(items=[BatchRead.from_row(batch) for batch in batches])


@router.get("/batches/{batch_id}", response_model=BatchRead)
async def get_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _JOB_READ,
) -> BatchRead:
    batch = await batch_service.get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return BatchRead.from_row(batch)


@router.get("/batches/{batch_id}/staged", response_model=StagedDocumentList)
async def list_staged(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _STAGED_READ,
) -> StagedDocumentList:
    """Preview what a batch staged.

    This is the only endpoint that can see ``published = false`` rows.
    It is gated by ``rag_governance:staged:read`` rather than
    ``project:read`` because the preview deliberately shows documents
    above the caller's clearance: an approver cannot judge a batch they
    are only allowed to see part of.
    """
    batch = await batch_service.get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    project = await project_service.get_project(db, batch.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    documents = await batch_service.list_staged_documents(db, project, batch)
    return StagedDocumentList(
        items=[StagedDocumentRead.from_row(document) for document in documents]
    )
