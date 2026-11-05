"""Golden dataset endpoints: import, export, edit, confirm, fork.

Editing is deliberately two-step. ``PUT /golden/{id}`` only accepts a
candidate set; editing a confirmed set returns 409 and the client must
``POST /golden/{id}/fork`` first. That keeps the promise the evaluation
history depends on: a report that names set 3 version 1 keeps pointing
at the exact cases it ran.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.golden import (
    GoldenSetNotFoundError,
    GoldenValidationError,
    GoldenVersionError,
    confirm_set,
    create_candidate_set,
    dump_jsonl,
    fork_set,
    list_sets,
    load_cases,
    parse_jsonl,
    replace_cases,
)
from cliver_playbook.app.rag_governance.golden import versions as version_service
from cliver_playbook.app.rag_governance.runtime import enqueue
from cliver_playbook.app.rag_governance.schemas.golden import (
    GoldenGenerateRequest,
    GoldenImportRequest,
    GoldenJobAccepted,
    GoldenSetList,
    GoldenSetRead,
    GoldenSetUpdate,
)
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_READ = Security(require_perm("rag_governance:golden:read"))
_WRITE = Security(require_perm("rag_governance:golden:write"))


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, GoldenSetNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, GoldenVersionError):
        return HTTPException(status_code=409, detail=str(exc))
    assert isinstance(exc, GoldenValidationError)
    return HTTPException(status_code=422, detail=str(exc))


async def _set_response(db: AsyncSession, set_id: str) -> GoldenSetRead:
    golden_set = await version_service.get_set_or_raise(db, set_id)
    cases = await load_cases(db, set_id)
    return GoldenSetRead.from_row(golden_set, cases)


@router.get("/projects/{project_id}/golden", response_model=GoldenSetList)
async def list_golden_sets(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> GoldenSetList:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    items = [
        GoldenSetRead.from_row(golden_set, await load_cases(db, golden_set.id))
        for golden_set in await list_sets(db, project_id)
    ]
    return GoldenSetList(items=items)


@router.post(
    "/projects/{project_id}/golden/generate",
    status_code=202,
    response_model=GoldenJobAccepted,
)
async def generate_golden(
    project_id: str,
    payload: GoldenGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _WRITE,
) -> GoldenJobAccepted:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="project is archived")
    job = await enqueue(
        db,
        project_id=project.id,
        kind="generate_golden",
        payload={
            "project_id": project.id,
            "scenario": payload.scenario,
            "max_cases": payload.max_cases,
        },
    )
    await db.commit()
    return GoldenJobAccepted(job_id=job.id, kind=job.kind, status=job.status)


@router.post(
    "/projects/{project_id}/golden/import",
    status_code=201,
    response_model=GoldenSetRead,
)
async def import_golden(
    project_id: str,
    payload: GoldenImportRequest,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> GoldenSetRead:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        cases = parse_jsonl(payload.jsonl)
        golden_set = await create_candidate_set(
            db, project.id, cases, actor=viewer.username, source="import"
        )
    except (GoldenValidationError, GoldenVersionError) as exc:
        raise _http_error(exc) from None
    return GoldenSetRead.from_row(golden_set, cases)


@router.get("/golden/{set_id}", response_model=GoldenSetRead)
async def get_golden_set(
    set_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> GoldenSetRead:
    try:
        return await _set_response(db, set_id)
    except (GoldenSetNotFoundError, GoldenVersionError, GoldenValidationError) as exc:
        raise _http_error(exc) from None


@router.put("/golden/{set_id}", response_model=GoldenSetRead)
async def update_golden_set(
    set_id: str,
    payload: GoldenSetUpdate,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> GoldenSetRead:
    try:
        golden_set = await replace_cases(db, set_id, payload.cases, actor=viewer.username)
        cases = await load_cases(db, golden_set.id)
    except (GoldenSetNotFoundError, GoldenVersionError, GoldenValidationError) as exc:
        raise _http_error(exc) from None
    return GoldenSetRead.from_row(golden_set, cases)


@router.post("/golden/{set_id}/confirm", response_model=GoldenSetRead)
async def confirm_golden_set(
    set_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> GoldenSetRead:
    try:
        await confirm_set(db, set_id, actor=viewer.username)
        return await _set_response(db, set_id)
    except (GoldenSetNotFoundError, GoldenVersionError, GoldenValidationError) as exc:
        raise _http_error(exc) from None


@router.post("/golden/{set_id}/fork", response_model=GoldenSetRead)
async def fork_golden_set(
    set_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> GoldenSetRead:
    try:
        golden_set = await fork_set(db, set_id, actor=viewer.username)
        return await _set_response(db, golden_set.id)
    except (GoldenSetNotFoundError, GoldenVersionError, GoldenValidationError) as exc:
        raise _http_error(exc) from None


@router.get("/golden/{set_id}/export", response_class=PlainTextResponse)
async def export_golden_set(
    set_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> PlainTextResponse:
    try:
        golden_set = await version_service.get_set_or_raise(db, set_id)
        cases = await load_cases(db, set_id)
    except (GoldenSetNotFoundError, GoldenVersionError, GoldenValidationError) as exc:
        raise _http_error(exc) from None
    return PlainTextResponse(
        dump_jsonl(cases),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="golden-v{golden_set.version}.jsonl"'
        },
    )
