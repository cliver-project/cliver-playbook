"""Wire models for the governed query endpoint.

The response exposes the provenance the UI needs: the strategy that
actually ran, document and tool citations, and one record per tool
call with its ``as_of`` and failure state. The evaluator-facing
observation stays server-side.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cliver_playbook.app.rag_governance.query.facade import Answer


class QueryRequest(BaseModel):
    """One question to one governance project."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    # Omitted means "the request time", supplied by the API boundary.
    # The facade itself never reads a clock.
    as_of: datetime | None = None

    @field_validator("as_of")
    @classmethod
    def _aware_as_of(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value


class CitationRead(BaseModel):
    kind: Literal["document", "tool"]
    ref: str
    locator: str | None = None
    as_of: datetime | None = None


class ToolCallRead(BaseModel):
    name: str
    args_fingerprint: str
    as_of: datetime
    row_count: int
    latency_ms: int
    error: str | None
    is_snapshot: bool
    period: str | None


class QueryResponse(BaseModel):
    text: str
    intent: str | None
    strategy: str
    citations: list[CitationRead]
    tool_calls: list[ToolCallRead]
    as_of: datetime
    refused: bool
    rule_version: int | None

    @classmethod
    def from_answer(cls, answer: Answer) -> QueryResponse:
        return cls(
            text=answer.text,
            intent=answer.intent,
            strategy=answer.strategy,
            citations=[
                CitationRead(
                    kind=citation.kind,
                    ref=citation.ref,
                    locator=citation.locator,
                    as_of=citation.as_of,
                )
                for citation in answer.citations
            ],
            tool_calls=[
                ToolCallRead(
                    name=record.name,
                    args_fingerprint=record.args_fingerprint,
                    as_of=record.as_of,
                    row_count=record.row_count,
                    latency_ms=record.latency_ms,
                    error=record.error,
                    is_snapshot=record.is_snapshot,
                    period=record.period,
                )
                for record in answer.tool_calls
            ],
            as_of=answer.as_of,
            refused=answer.refused,
            rule_version=answer.rule_version,
        )
