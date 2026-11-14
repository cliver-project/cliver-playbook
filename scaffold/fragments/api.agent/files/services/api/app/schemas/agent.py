"""Agent run, collaboration and self-enhancement contract shapes."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = Field(default=None, max_length=200)
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


class AgentRuntimeStatusRead(BaseModel):
    model_configured: bool
    judge_enabled: bool
    mcp_enabled: bool
    compaction_enabled: bool
    tool_permission_mode: str
    system_one_provider: str
    model_provider: str = ""
    model_name: str = ""
    mcp_servers: list[str] = Field(default_factory=list)


class AgentSessionRead(BaseModel):
    session_id: str
    last_message: str
    run_count: int = Field(ge=1)
    updated_at: datetime


class AgentSessionList(BaseModel):
    sessions: list[AgentSessionRead]


class AgentSessionRunRead(BaseModel):
    run_id: str
    message: str
    status: str
    created_at: datetime
    events: list[dict[str, Any]] = Field(default_factory=list)


class AgentSessionDetail(BaseModel):
    session_id: str
    runs: list[AgentSessionRunRead]


class AgentFeedbackRequest(BaseModel):
    agent: str = Field(min_length=1, max_length=64)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)
    step: int | None = Field(default=None, ge=0, le=2**31 - 1)


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


class AgentGoldenSetPublishRequest(BaseModel):
    agent: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=2000)


class AgentGoldenSetVersionRead(BaseModel):
    id: int
    agent: str
    version: int
    cases: list[dict[str, Any]]
    note: str
    created_by: int | None = None
    is_active: bool
    created_at: datetime


class AgentGoldenSetVersionList(BaseModel):
    versions: list[AgentGoldenSetVersionRead]


class AgentConfigVersionRead(BaseModel):
    id: int
    agent: str
    version: int
    prompt_overlay: str
    rollout_percent: int = 100
    source_proposal_id: str | None = None
    note: str
    created_by: int | None = None
    created_at: datetime


class AgentConfigVersionList(BaseModel):
    versions: list[AgentConfigVersionRead]


class AgentConfigRollbackRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


class AgentConfigRolloutRequest(BaseModel):
    percent: int = Field(ge=0, le=100)
    note: str = Field(default="", max_length=2000)


class AgentLearningSummaryRead(BaseModel):
    agent: str
    config_version: int | None = None
    config_versions: int
    prompt_overlay: str
    rollout_percent: int = 100
    active_golden_version: int | None = None
    golden_versions: int
    proposal_counts: dict[str, int]
    feedback_count: int
    positive_feedback: int
    recent_pass_rate: float | None = None
    recent_evaluations: int
    generated_at: datetime


class AgentProposalDecision(BaseModel):
    proposal: AgentProposalRead
    applied: bool
    requires_manual_apply: bool
    regression: AgentRegressionRead | None = None


class AgentProposalRejectRequest(BaseModel):
    note: str = Field(default="", max_length=2000)
