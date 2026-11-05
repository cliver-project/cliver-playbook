"""Wire models for approval decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cliver_playbook.app.rag_governance.models.entities import GovApproval
from cliver_playbook.app.rag_governance.schemas.batches import BatchRead


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=4000)


class ApprovalRead(BaseModel):
    id: str
    batch_id: str
    decision: str
    comment: str
    actor_id: str
    created_at: datetime | None

    @classmethod
    def from_row(cls, approval: GovApproval) -> ApprovalRead:
        return cls(
            id=approval.id,
            batch_id=approval.batch_id,
            decision=approval.decision,
            comment=approval.comment,
            actor_id=approval.actor_id,
            created_at=approval.created_at,
        )


class ApprovalResult(BaseModel):
    batch: BatchRead
    approval: ApprovalRead


class ApprovalList(BaseModel):
    items: list[ApprovalRead]
