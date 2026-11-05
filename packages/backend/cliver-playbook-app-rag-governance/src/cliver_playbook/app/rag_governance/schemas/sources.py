"""Wire models for sources and the ingest trigger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cliver_playbook.app.rag_governance.models.entities import GovSource


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=32)
    config: dict[str, Any] = Field(default_factory=dict)
    authority: str = Field(default="document", min_length=1, max_length=32)
    sync_schedule: str | None = Field(default=None, max_length=64)
    sync_enabled: bool = False
    max_staleness_seconds: int | None = Field(default=None, ge=0)


class SourceRead(BaseModel):
    id: str
    project_id: str
    kind: str
    config: dict[str, Any]
    authority: str
    sync_schedule: str | None
    sync_enabled: bool
    max_staleness_seconds: int | None
    status: str
    last_run_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, source: GovSource) -> SourceRead:
        return cls(
            id=source.id,
            project_id=source.project_id,
            kind=source.kind,
            config=source.config_json,
            authority=source.authority,
            sync_schedule=source.sync_schedule,
            sync_enabled=source.sync_enabled,
            max_staleness_seconds=source.max_staleness_seconds,
            status=source.status,
            last_run_at=source.last_run_at,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


class SourceList(BaseModel):
    items: list[SourceRead]


class IngestRequest(BaseModel):
    """Reserved for per-run overrides; empty in v1."""

    model_config = ConfigDict(extra="forbid")


class IngestAccepted(BaseModel):
    batch_id: str
    job_id: str
    kind: str
    status: str
