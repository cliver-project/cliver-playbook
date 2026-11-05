"""Intent-rule endpoints: propose, preview and the activation gate.

``activate`` requires an evaluation run id in the body, but the run is
re-read server-side and checked against the project's current confirmed
golden set. Passing an id from another project, a failed run, or a run
against an older set is a 409 — the client cannot talk its way past the
gate.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag_governance.rules import (
    KeywordRegexClassifier,
    RuleActivationError,
    RuleCompileError,
    RuleValidationError,
    activate_rule_set,
    active_rule_set,
    compile_rule_scope,
    create_rule_set,
    list_rule_sets,
    rank_matches,
)
from cliver_playbook.app.rag_governance.schemas.rules import (
    RuleMatchRead,
    RulePreviewRead,
    RulePreviewRequest,
    RuleSetActivate,
    RuleSetList,
    RuleSetPropose,
    RuleSetRead,
)
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_READ = Security(require_perm("rag_governance:rule:read"))
_WRITE = Security(require_perm("rag_governance:rule:write"))


def _raise_rule_error(exc: Exception) -> None:
    if isinstance(exc, RuleActivationError):
        raise HTTPException(status_code=409, detail=str(exc)) from None
    assert isinstance(exc, (RuleValidationError, RuleCompileError))
    raise HTTPException(status_code=422, detail=str(exc)) from None


async def _project_or_404(db: AsyncSession, project_id: str):
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}/rules", response_model=RuleSetRead)
async def get_active_rules(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> RuleSetRead:
    project = await _project_or_404(db, project_id)
    return RuleSetRead.from_version(project.id, await active_rule_set(db, project_id))


@router.get("/projects/{project_id}/rules/versions", response_model=RuleSetList)
async def list_rule_versions(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> RuleSetList:
    project = await _project_or_404(db, project_id)
    return RuleSetList(
        items=[
            RuleSetRead.from_version(project.id, rule_set)
            for rule_set in await list_rule_sets(db, project_id)
        ]
    )


@router.post(
    "/projects/{project_id}/rules/propose",
    status_code=201,
    response_model=RuleSetRead,
)
async def propose_rules(
    project_id: str,
    payload: RuleSetPropose,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> RuleSetRead:
    project = await _project_or_404(db, project_id)
    try:
        rule_set = await create_rule_set(db, project.id, payload.rules, actor=viewer.username)
    except (RuleValidationError, RuleCompileError) as exc:
        _raise_rule_error(exc)
    return RuleSetRead.from_version(project.id, rule_set)


@router.post("/projects/{project_id}/rules/activate", response_model=RuleSetRead)
async def activate_rules(
    project_id: str,
    payload: RuleSetActivate,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> RuleSetRead:
    project = await _project_or_404(db, project_id)
    try:
        rule_set = await activate_rule_set(
            db,
            project.id,
            payload.rules,
            eval_run_id=payload.eval_run_id,
            actor=viewer.username,
        )
    except (RuleActivationError, RuleValidationError, RuleCompileError) as exc:
        _raise_rule_error(exc)
    return RuleSetRead.from_version(project.id, rule_set)


@router.post("/projects/{project_id}/rules/preview", response_model=RulePreviewRead)
async def preview_rules(
    project_id: str,
    payload: RulePreviewRequest,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> RulePreviewRead:
    await _project_or_404(db, project_id)
    rules = payload.rules
    if rules is None:
        active = await active_rule_set(db, project_id)
        rules = active.rules if active else []
    try:
        for rule in rules:
            compile_rule_scope(rule)
    except (RuleValidationError, RuleCompileError) as exc:
        _raise_rule_error(exc)
    matches = rank_matches(KeywordRegexClassifier().classify(payload.question, rules))
    return RulePreviewRead(
        matches=[
            RuleMatchRead(
                intent=match.intent,
                confidence=round(match.confidence, 4),
                priority=match.rule.priority,
                strategy=match.rule.strategy,
            )
            for match in matches
        ]
    )
