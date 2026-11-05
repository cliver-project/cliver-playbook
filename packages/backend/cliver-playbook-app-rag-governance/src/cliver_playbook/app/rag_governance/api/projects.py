"""Project endpoints: create, list, read, update."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.schemas.projects import (
    ProjectCreate,
    ProjectList,
    ProjectRead,
    ProjectUpdate,
)
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_READ = Security(require_perm("rag_governance:project:read"))
_WRITE = Security(require_perm("rag_governance:project:write"))


@router.post("/projects", status_code=201, response_model=ProjectRead)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> ProjectRead:
    try:
        project = await project_service.create_project(
            db,
            slug=payload.slug,
            name=payload.name,
            approval_mode=payload.approval_mode,
            description=payload.description,
            collection_id=payload.collection_id,
            config=payload.config,
            actor=viewer.username,
        )
    except project_service.ProjectSlugTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except project_service.ProjectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ProjectRead.from_row(project)


@router.get("/projects", response_model=ProjectList)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> ProjectList:
    projects = await project_service.list_projects(db)
    return ProjectList(items=[ProjectRead.from_row(project) for project in projects])


async def _project_or_404(db: AsyncSession, project_id: str):
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> ProjectRead:
    return ProjectRead.from_row(await _project_or_404(db, project_id))


@router.put("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> ProjectRead:
    project = await _project_or_404(db, project_id)
    try:
        project = await project_service.update_project(
            db,
            project,
            name=payload.name,
            description=payload.description,
            approval_mode=payload.approval_mode,
            config=payload.config,
            actor=viewer.username,
        )
    except project_service.ProjectValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ProjectRead.from_row(project)
