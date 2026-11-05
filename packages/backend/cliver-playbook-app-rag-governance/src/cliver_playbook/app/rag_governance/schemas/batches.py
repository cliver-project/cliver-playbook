"""Wire models for ingest batches and the staged preview."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag_governance.models.entities import GovIngestBatch


class BatchRead(BaseModel):
    id: str
    project_id: str
    source_id: str | None
    status: str
    stats: dict[str, Any]
    eval_run_id: str | None
    submitted_by: str
    approved_by: str | None
    approved_at: datetime | None
    comment: str | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, batch: GovIngestBatch) -> BatchRead:
        return cls(
            id=batch.id,
            project_id=batch.project_id,
            source_id=batch.source_id,
            status=batch.status,
            stats=batch.stats_json,
            eval_run_id=batch.eval_run_id,
            submitted_by=batch.submitted_by,
            approved_by=batch.approved_by,
            approved_at=batch.approved_at,
            comment=batch.comment,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )


class BatchList(BaseModel):
    items: list[BatchRead]


class StagedDocumentRead(BaseModel):
    """One staged document. The preview carries metadata, not text."""

    id: str
    logical_id: str | None
    version: int
    title: str
    source_uri: str | None
    mime_type: str
    classification: int | None
    published: bool
    chunk_count: int
    metadata: dict[str, Any]
    created_at: datetime | None

    @classmethod
    def from_row(cls, document: Document) -> StagedDocumentRead:
        return cls(
            id=document.id,
            logical_id=document.logical_id,
            version=document.version,
            title=document.title,
            source_uri=document.source_uri,
            mime_type=document.mime_type,
            classification=document.classification,
            published=document.published,
            chunk_count=document.chunk_count,
            metadata=document.metadata_json,
            created_at=document.created_at,
        )


class StagedDocumentList(BaseModel):
    items: list[StagedDocumentRead]
