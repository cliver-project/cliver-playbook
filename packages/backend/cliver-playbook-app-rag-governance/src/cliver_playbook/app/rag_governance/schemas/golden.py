"""Wire models for golden datasets."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cliver_playbook.app.rag_governance.golden.schema import GoldenCase
from cliver_playbook.app.rag_governance.models.entities import GovGoldenSet


class GoldenSetRead(BaseModel):
    id: str
    project_id: str
    version: int
    status: str
    source: str
    created_by: str
    confirmed_by: str | None
    created_at: datetime | None
    updated_at: datetime | None
    cases: list[GoldenCase]

    @classmethod
    def from_row(cls, golden_set: GovGoldenSet, cases: list[GoldenCase]) -> GoldenSetRead:
        return cls(
            id=golden_set.id,
            project_id=golden_set.project_id,
            version=golden_set.version,
            status=golden_set.status,
            source=golden_set.source,
            created_by=golden_set.created_by,
            confirmed_by=golden_set.confirmed_by,
            created_at=golden_set.created_at,
            updated_at=golden_set.updated_at,
            cases=cases,
        )


class GoldenSetList(BaseModel):
    items: list[GoldenSetRead]


class GoldenSetUpdate(BaseModel):
    """Replace every case in a candidate set."""

    model_config = ConfigDict(extra="forbid")

    cases: list[GoldenCase] = Field(min_length=1)


class GoldenImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonl: str = Field(min_length=1)


class GoldenGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(default="", max_length=4000)
    max_cases: int = Field(default=10, ge=1, le=100)


class GoldenJobAccepted(BaseModel):
    job_id: str
    kind: str
    status: str
