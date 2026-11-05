"""Wire models for evaluation runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cliver_playbook.app.rag_governance.models.entities import GovEvalRun


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    golden_set_id: str = Field(min_length=1, max_length=36)
    rule_version: int | None = Field(default=None, ge=1)
    stage: str = Field(default="baseline", min_length=1, max_length=32)
    reference_time: AwareDatetime | None = None


class EvaluationAccepted(BaseModel):
    job_id: str
    kind: str
    status: str


class EvaluationRunRead(BaseModel):
    id: str
    project_id: str
    golden_set_id: str
    rule_version: int | None
    stage: str
    status: str
    metrics: dict[str, float]
    summary: str
    created_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_row(cls, run: GovEvalRun) -> EvaluationRunRead:
        report = run.report_json or {}
        return cls(
            id=run.id,
            project_id=run.project_id,
            golden_set_id=run.golden_set_id,
            rule_version=run.rule_version,
            stage=run.stage,
            status=run.status,
            metrics=run.metrics_json or {},
            summary=str(report.get("summary", "")),
            created_at=run.created_at,
            finished_at=run.finished_at,
        )


class EvaluationRunList(BaseModel):
    items: list[EvaluationRunRead]


class EvaluationCaseRead(BaseModel):
    case_id: str
    passed: bool
    details: dict[str, Any]


class EvaluationRunDetail(EvaluationRunRead):
    cases: list[EvaluationCaseRead]
