"""Governed query endpoint.

The endpoint is a thin boundary: it resolves the project, chooses the
process-wide LLM, injects the request time as ``as_of`` and delegates to
the facade. The tool registry and planner live on ``app.state`` so a
composition root (or the finance scenario) can register implementations
without the governance package importing scenario code.

Error mapping keeps the failure modes distinguishable: a missing active
rule set or tool profile is a 409 (the project is not ready to serve),
and a planner that requests an unauthorized tool is also a 409 — never
a silent less-privileged answer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import write_rag_audit
from cliver_playbook.app.rag.llm import get_llm
from cliver_playbook.app.rag.settings import settings as rag_settings
from cliver_playbook.app.rag_governance.query.facade import (
    QueryConfigError,
    QueryToolError,
    ToolPlanner,
    answer_question,
)
from cliver_playbook.app.rag_governance.schemas.query import QueryRequest, QueryResponse
from cliver_playbook.app.rag_governance.services import projects as project_service
from cliver_playbook.app.rag_governance.tools.registry import ToolRegistry
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag-governance", tags=["rag-governance"])

_QUERY = Security(require_perm("rag_governance:query:read"))


def _audit_sink(viewer: Viewer, request: Request):
    async def sink(record: dict) -> None:
        await write_rag_audit(
            event="governance.query",
            target=record["question_fingerprint"],
            ok=not record["refused"],
            args={
                "project_id": record["project_id"],
                "intent": record["intent"],
                "strategy": record["strategy"],
                "rule_version": record["rule_version"],
            },
            extra={
                "as_of": record["as_of"],
                "refused": record["refused"],
                "retrieval_calls": record["retrieval_calls"],
                "hit_ids": record["hit_chunk_ids"],
                "citations": record["citations"],
                "tool_calls": record["tool_calls"],
                "model_id": record["model_id"],
            },
            viewer=viewer,
            request=request,
        )

    return sink


@router.post("/projects/{project_id}/query", response_model=QueryResponse)
async def query_project(
    project_id: str,
    payload: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _QUERY,
) -> QueryResponse:
    project = await project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    registry: ToolRegistry | None = getattr(request.app.state, "tool_registry", None)
    planner: ToolPlanner | None = getattr(request.app.state, "tool_planner", None)
    llm = get_llm(rag_settings.rag.llm)
    as_of = payload.as_of or datetime.now(UTC)

    try:
        answer = await answer_question(
            db,
            project=project,
            question=payload.question,
            viewer=viewer,
            as_of=as_of,
            llm=llm,
            tool_registry=registry,
            planner=planner,
            audit=_audit_sink(viewer, request),
        )
    except (QueryConfigError, QueryToolError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return QueryResponse.from_answer(answer)
