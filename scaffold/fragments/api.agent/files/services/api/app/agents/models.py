"""Project-owned persistence for agent run state and events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AgentRun(Base):
    """One coordinator run, durable across requests and restarts."""

    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    cancelled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentRunEvent(Base):
    """One persisted run event; (run_id, sequence) is the replay order."""

    __tablename__ = "agent_run_events"

    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentExperience(Base):
    """One redacted observation of a sub-agent result.

    This is the raw material of the learning loop, not a chat transcript. The
    pipeline applies the agent's source policy and PII redaction before insert;
    retention pruning removes rows older than the policy allows.
    """

    __tablename__ = "agent_experiences"
    __table_args__ = (UniqueConstraint("run_id", "step", "agent", name="uq_agent_experience_step"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class AgentFeedback(Base):
    """A user's outcome rating for one observed result."""

    __tablename__ = "agent_feedback"
    __table_args__ = (
        UniqueConstraint("experience_id", "user_id", name="uq_agent_feedback_user"),
        Index(
            "uq_agent_feedback_anonymous",
            "experience_id",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experience_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentEvaluation(Base):
    """The latest evaluation of one experience for one metric."""

    __tablename__ = "agent_evaluations"
    __table_args__ = (
        UniqueConstraint("experience_id", "metric", name="uq_agent_evaluation_metric"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experience_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentImprovement(Base):
    """A reviewed prompt/tool/policy proposal emitted by the learning loop."""

    __tablename__ = "agent_improvements"
    __table_args__ = (
        Index(
            "uq_agent_improvement_pending",
            "agent",
            "kind",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="prompt")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    patch: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentImprovementEvent(Base):
    """Append-only audit trail for proposal creation and review."""

    __tablename__ = "agent_improvement_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("agent_improvements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentConfig(Base):
    """The active, approved runtime guidance for one sub-agent."""

    __tablename__ = "agent_configs"

    agent: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_overlay: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rollout_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentGoldenCase(Base):
    """One offline regression case for a sub-agent."""

    __tablename__ = "agent_golden_cases"
    __table_args__ = (UniqueConstraint("agent", "name", name="uq_agent_golden_case_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected_contains: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    forbidden_contains: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentGoldenSetVersion(Base):
    """An immutable snapshot of an agent's enabled golden cases."""

    __tablename__ = "agent_golden_set_versions"
    __table_args__ = (
        UniqueConstraint("agent", "version", name="uq_agent_golden_set_version"),
        Index(
            "uq_agent_golden_set_active",
            "agent",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    cases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentConfigVersion(Base):
    """Append-only prompt-overlay history for rollback and audit."""

    __tablename__ = "agent_config_versions"
    __table_args__ = (UniqueConstraint("agent", "version", name="uq_agent_config_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_overlay: Mapped[str] = mapped_column(Text, nullable=False)
    rollout_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    source_proposal_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentRegressionRun(Base):
    """The latest offline gate result for one improvement proposal."""

    __tablename__ = "agent_regression_runs"
    __table_args__ = (UniqueConstraint("proposal_id", name="uq_agent_regression_proposal"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("agent_improvements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    baseline_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    candidate_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    min_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    case_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
