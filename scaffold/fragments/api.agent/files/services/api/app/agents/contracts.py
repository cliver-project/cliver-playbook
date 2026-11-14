"""Contracts for the API plane's coordinator and business-point sub-agents.

This module is the seam ADR-0027 describes. The coordinator, registry,
sub-agents and pipeline implementations depend on these types, not on each
other's internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cliver_core import CLIverTool


@dataclass(frozen=True)
class AgentIntent:
    """A coordinator decision to delegate work to one sub-agent."""

    name: str
    confidence: float = 1.0
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("AgentIntent.name must not be blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AgentIntent.confidence must be between 0 and 1")


@dataclass
class AgentContext:
    """Everything a sub-agent needs for one run.

    ``resources`` is the seam for services the coordinator owns: a database
    session, a model client, a clock, a telemetry sink. Sub-agents never reach
    for process globals. In a multi-step plan the coordinator fills
    ``prior_results`` before each step, so a sub-agent (or its model prompt)
    can build on what earlier steps produced. ``step`` identifies the
    per-step learning record; the coordinator owns it.
    """

    run_id: str
    message: str
    user_id: int | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    prior_results: list[AgentResult] = field(default_factory=list)
    step: int = 0


@dataclass
class AgentResult:
    """The business-point result returned to the coordinator."""

    agent: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentToolkit:
    """The tools and prompt a sub-agent contributes to one AgentCore run.

    Tools are built per run because they may close over request-scoped
    resources (a database session). Read-only tools should declare
    ``safety="safe"``; mutating tools stay behind the permission callback.
    ``mcp_servers`` names the MCP servers this agent may call; an empty list
    falls back to the run-level servers from ``context.resources``.
    """

    system_prompt: str
    tools: list[CLIverTool] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    # Set by the runner when a sub-agent omits it, so Core can scope skills.
    agent_name: str = ""


@dataclass(frozen=True)
class AutonomyPolicy:
    """What a sub-agent may observe and improve from.

    ``allowed_sources`` is a data-autonomy allow-list: when it is non-empty,
    the run must declare its source tags in ``context.metadata["sources"]``
    and every tag must be allowed, or the observation is dropped. An empty
    allow-list means the agent has no external-source restriction. The
    learning pipeline also redacts sensitive keys and text and prunes
    experiences after ``retention_days``.

    ``evaluation_threshold`` is the launch bar (0.6 = "60 points"). A result
    below it is a failed evaluation and can become a proposal. When golden
    cases exist, approval also requires the candidate overlay to meet
    ``regression_min_score`` without regressing below the current overlay.
    ``auto`` still requires approval; the reference implementation treats it
    as ``proposal``.
    """

    allowed_sources: tuple[str, ...] = ()
    feedback_dataset: str | None = None
    evaluation_metric: str | None = None
    evaluation_threshold: float = 0.6
    regression_min_score: float = 0.8
    improvement_mode: str = "off"  # off | proposal | auto
    require_approval: bool = True
    retention_days: int = 30

    def __post_init__(self) -> None:
        if self.improvement_mode not in {"off", "proposal", "auto"}:
            raise ValueError("AutonomyPolicy.improvement_mode must be off, proposal or auto")
        if self.improvement_mode == "auto" and not self.require_approval:
            raise ValueError("automatic improvement requires approval")
        if not 0.0 < self.evaluation_threshold <= 1.0:
            raise ValueError("AutonomyPolicy.evaluation_threshold must be in (0, 1]")
        if not 0.0 <= self.regression_min_score <= 1.0:
            raise ValueError("AutonomyPolicy.regression_min_score must be in [0, 1]")
        if self.retention_days < 1:
            raise ValueError("AutonomyPolicy.retention_days must be at least 1")


@runtime_checkable
class SelfEnhancingPipeline(Protocol):
    """The per-sub-agent learning loop; the scaffold ships LearningPipeline."""

    async def observe(self, context: AgentContext, result: AgentResult) -> None: ...

    async def evaluate(self, context: AgentContext, result: AgentResult) -> dict[str, Any]: ...

    async def improve(
        self, context: AgentContext, evaluation: dict[str, Any]
    ) -> dict[str, Any] | None: ...


@runtime_checkable
class SubAgent(Protocol):
    """One business point in the collaboration platform."""

    name: str
    description: str
    capabilities: tuple[str, ...]
    autonomy: AutonomyPolicy
    pipeline: SelfEnhancingPipeline

    def can_handle(self, intent: AgentIntent) -> bool: ...

    def toolkit(self, context: AgentContext) -> AgentToolkit: ...

    async def run(self, context: AgentContext) -> AgentResult: ...


@dataclass(frozen=True)
class AgentDescriptor:
    """The public, serializable view of a registered sub-agent."""

    name: str
    description: str
    capabilities: tuple[str, ...]
    autonomy_mode: str
    has_pipeline: bool
