"""Evaluation endpoints: start a run as a durable job, then read reports.

The HTTP request does not run the suite: evaluation replays every case,
may call live tools and can take minutes, so it is enqueued like any
other long job. The worker handler (registered by the composition root
once the query facade exists) reads the same payload and calls
``run_evaluation``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.golden import get_set
from cliver_playbook.app.rag_governance.models.entities import GovEvalCaseResult, GovEvalRun
from cliver_playbook.app.rag_governance.rules import get_rule_set
from cliver_playbook.app.rag_governance.runtime import enqueue
from cliver_playbook.app.rag_governance.schemas.evaluations import (
    EvaluationAccepted,
    EvaluationCaseRead,
    EvaluationRequest,
    EvaluationRunDetail,
    EvaluationRunList,
    EvaluationRunRead,
)
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_READ = Security(require_perm("rag_governance:eval:read"))
_RUN = Security(require_perm("rag_governance:eval:run"))


async def _project_or_404(db: AsyncSession, project_id: str):
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.post(
    "/projects/{project_id}/evaluations",
    status_code=202,
    response_model=EvaluationAccepted,
)
async def start_evaluation(
    project_id: str,
    payload: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _RUN,
) -> EvaluationAccepted:
    project = await _project_or_404(db, project_id)
    golden_set = await get_set(db, payload.golden_set_id)
    if golden_set is None or golden_set.project_id != project.id:
        raise HTTPException(status_code=404, detail="golden set not found")
    if golden_set.status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="evaluation runs require a confirmed golden set",
        )
    if payload.rule_version is not None:
        rule_set = await get_rule_set(db, project.id, payload.rule_version)
        if rule_set is None:
            raise HTTPException(status_code=404, detail="rule set not found")

    job = await enqueue(
        db,
        project_id=project.id,
        kind="run_eval",
        payload={
            "project_id": project.id,
            "golden_set_id": golden_set.id,
            "rule_version": payload.rule_version,
            "stage": payload.stage,
            "reference_time": (
                payload.reference_time.isoformat() if payload.reference_time else None
            ),
        },
    )
    await db.commit()
    return EvaluationAccepted(job_id=job.id, kind=job.kind, status=job.status)


@router.get("/projects/{project_id}/evaluations", response_model=EvaluationRunList)
async def list_evaluations(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> EvaluationRunList:
    await _project_or_404(db, project_id)
    rows = (
        (
            await db.execute(
                select(GovEvalRun)
                .where(GovEvalRun.project_id == project_id)
                .order_by(GovEvalRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return EvaluationRunList(items=[EvaluationRunRead.from_row(run) for run in rows])


@router.get("/evaluations/{run_id}", response_model=EvaluationRunDetail)
async def get_evaluation(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> EvaluationRunDetail:
    run = await db.get(GovEvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    rows = (
        (
            await db.execute(
                select(GovEvalCaseResult)
                .where(GovEvalCaseResult.run_id == run_id)
                .order_by(GovEvalCaseResult.case_id)
            )
        )
        .scalars()
        .all()
    )
    return EvaluationRunDetail(
        **EvaluationRunRead.from_row(run).model_dump(),
        cases=[
            EvaluationCaseRead(
                case_id=row.case_id,
                passed=row.passed,
                details=row.details_json or {},
            )
            for row in rows
        ],
    )
