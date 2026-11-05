"""Approval endpoints: decide a staged batch, then read its history.

The route gates ``rag_governance:approve`` and supplies the caller's
effective clearance; the service owns the gates and the publish
transaction. A hard-gate failure is a 409, never a silent publish.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.schemas.approvals import (
    ApprovalDecisionRequest,
    ApprovalList,
    ApprovalRead,
    ApprovalResult,
)
from cliver_playbook.app.rag_governance.schemas.batches import BatchRead
from cliver_playbook.app.rag_governance.services import access as access_service
from cliver_playbook.app.rag_governance.services import approvals as approval_service
from cliver_playbook.app.rag_governance.services import batches as batch_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_APPROVE = Security(require_perm("rag_governance:approve"))


@router.post("/batches/{batch_id}/approval", response_model=ApprovalResult)
async def decide_batch(
    batch_id: str,
    payload: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _APPROVE,
) -> ApprovalResult:
    batch = await batch_service.get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    clearance = await access_service.effective_clearance(db, viewer)
    try:
        approval = await approval_service.decide(
            db,
            batch,
            decision=payload.decision,
            actor=viewer.username,
            comment=payload.comment,
            actor_clearance=clearance,
        )
    except approval_service.ApprovalBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except approval_service.ApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except approval_service.ApprovalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ApprovalResult(
        batch=BatchRead.from_row(batch),
        approval=ApprovalRead.from_row(approval),
    )


@router.get("/batches/{batch_id}/approvals", response_model=ApprovalList)
async def list_approvals(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _APPROVE,
) -> ApprovalList:
    batch = await batch_service.get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    approvals = await approval_service.list_approvals(db, batch_id)
    return ApprovalList(items=[ApprovalRead.from_row(row) for row in approvals])
