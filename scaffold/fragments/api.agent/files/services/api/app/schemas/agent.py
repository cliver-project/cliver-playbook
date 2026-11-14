"""Agent run, collaboration and self-enhancement contract shapes."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    attachments: list[str] = Field(default_factory=list)


class AgentRunCreated(BaseModel):
    run_id: str
    status: str


class AgentDescriptorRead(BaseModel):
    name: str
    description: str
    capabilities: list[str]
    autonomy_mode: str
    has_pipeline: bool


class AgentListRead(BaseModel):
    agents: list[AgentDescriptorRead]


class AgentFeedbackRequest(BaseModel):
    agent: str = Field(min_length=1, max_length=64)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)
    step: int | None = Field(default=None, ge=0)


class AgentProposalRead(BaseModel):
    id: str
    agent: str
    kind: str
    status: str
    title: str
    rationale: str
    patch: dict[str, Any]
    evidence: dict[str, Any]
    created_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None


class AgentProposalList(BaseModel):
    proposals: list[AgentProposalRead]


class AgentFeedbackCreated(BaseModel):
    feedback_id: int
    experience_id: int
    evaluation: dict[str, Any]
    proposal: AgentProposalRead | None = None


class AgentGoldenCaseCreate(BaseModel):
    agent: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)
    expected_contains: list[str] = Field(default_factory=list, max_length=20)
    forbidden_contains: list[str] = Field(default_factory=list, max_length=20)


class AgentGoldenCaseRead(BaseModel):
    id: int
    agent: str
    name: str
    message: str
    expected_contains: list[str]
    forbidden_contains: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentGoldenCaseList(BaseModel):
    cases: list[AgentGoldenCaseRead]


class AgentRegressionRead(BaseModel):
    id: int
    proposal_id: str
    agent: str
    status: str
    baseline_score: float
    candidate_score: float
    min_score: float
    case_results: list[dict[str, Any]]
    error: str
    created_at: datetime


class AgentProposalDecision(BaseModel):
    proposal: AgentProposalRead
    applied: bool
    requires_manual_apply: bool
    regression: AgentRegressionRead | None = None


class AgentProposalRejectRequest(BaseModel):
    note: str = Field(default="", max_length=2000)
