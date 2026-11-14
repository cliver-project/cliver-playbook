"""Planner seam: deterministic first, AgentCore when a model is configured.

The planner produces an ordered, multi-step plan over the registry — one
sub-agent per step. Model planning is advisory: any provider error, unknown
agent, empty or over-long plan falls back to the deterministic single-step
matcher, so a run never fails because routing did. The run/event contract does
not change.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from cliver_core import AgentCore, ModelBindings
from pydantic import BaseModel, Field

from app.agents.contracts import (
    AgentContext,
    AgentDescriptor,
    AgentIntent,
    SubAgent,
)
from app.agents.core import build_llm_binding
from app.settings import Settings

logger = logging.getLogger(__name__)


class PlanStepChoice(BaseModel):
    """One step of the structured answer the planner model must return."""

    agent: str = Field(description="Exact registered agent name.")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", description="One sentence explaining the step.")


class PlanChoice(BaseModel):
    """The structured answer the planner model must return."""

    steps: list[PlanStepChoice] = Field(min_length=1)


@dataclass(frozen=True)
class PlanDecision:
    """The ordered plan plus which planner produced it."""

    steps: tuple[AgentIntent, ...]
    planner: str
    fallback_reason: str | None = None


class Planner(Protocol):
    """The coordinator-facing planning seam."""

    async def plan(self, context: AgentContext, agents: Sequence[SubAgent]) -> PlanDecision: ...


def _descriptor(agent: SubAgent) -> AgentDescriptor:
    return AgentDescriptor(
        name=agent.name,
        description=agent.description,
        capabilities=tuple(agent.capabilities),
        autonomy_mode=agent.autonomy.improvement_mode,
        has_pipeline=agent.pipeline is not None,
    )


class DeterministicPlanner:
    """Keyword matching over the registry; always a single-step plan."""

    def __init__(self, *, default_agent: str = "general") -> None:
        self.default_agent = default_agent

    async def plan(self, context: AgentContext, agents: Sequence[SubAgent]) -> PlanDecision:
        for agent in agents:
            candidate = AgentIntent(
                name=agent.name,
                confidence=1.0,
                payload={"message": context.message, "planner": "deterministic"},
            )
            if agent.can_handle(candidate):
                return PlanDecision(steps=(candidate,), planner="deterministic")
        return PlanDecision(
            steps=(
                AgentIntent(
                    name=self.default_agent,
                    confidence=0.0,
                    payload={"message": context.message, "planner": "deterministic"},
                ),
            ),
            planner="deterministic",
        )


class PlanModel(Protocol):
    """The model-facing planning seam; a fake implements this in tests."""

    async def choose(self, message: str, agents: list[AgentDescriptor]) -> PlanChoice: ...


class AgentCorePlanModel:
    """Ask AgentCore for a structured, ordered plan."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def choose(self, message: str, agents: list[AgentDescriptor]) -> PlanChoice:
        binding = build_llm_binding(self.settings)
        if binding is None:
            raise RuntimeError("No API-plane model is configured")
        async with AgentCore.open(ModelBindings(llm=binding)) as agent:
            response = await agent.chat_structured(
                message,
                schema=PlanChoice,
                mode="auto",
                retries=1,
                system_prompt=_planner_prompt(agents),
                run_timeout=self.settings.agent_llm_timeout,
            )
        value = response.value
        if isinstance(value, PlanChoice):
            return value
        return PlanChoice.model_validate(value)


class AgentCorePlanner:
    """LLM multi-step planning with a deterministic fallback on every failure."""

    def __init__(
        self,
        model: PlanModel | None,
        *,
        fallback: Planner | None = None,
        max_steps: int = 8,
    ) -> None:
        self.model = model
        self.fallback = fallback or DeterministicPlanner()
        self.max_steps = max_steps

    async def plan(self, context: AgentContext, agents: Sequence[SubAgent]) -> PlanDecision:
        if self.model is None:
            return await self.fallback.plan(context, agents)
        known = {agent.name for agent in agents}
        try:
            choice = await self.model.choose(
                context.message, [_descriptor(agent) for agent in agents]
            )
            names = [step.agent for step in choice.steps]
            if not names:
                raise ValueError("planner returned an empty plan")
            unknown = sorted(set(names) - known)
            if unknown:
                raise ValueError(f"planner selected unknown agent(s) {unknown}")
            if len(names) > self.max_steps:
                raise ValueError(
                    f"planner returned {len(names)} steps; agent_plan_max_steps is {self.max_steps}"
                )
            return PlanDecision(
                steps=tuple(
                    AgentIntent(
                        name=step.agent,
                        confidence=step.confidence,
                        payload={
                            "message": context.message,
                            "reason": step.reason,
                            "planner": "agentcore",
                        },
                    )
                    for step in choice.steps
                ),
                planner="agentcore",
            )
        except Exception as exc:  # noqa: BLE001 — planning must fail open
            logger.warning("AgentCore planner fell back: %s", exc)
            decision = await self.fallback.plan(context, agents)
            return PlanDecision(
                steps=decision.steps,
                planner=decision.planner,
                fallback_reason=str(exc),
            )


def build_planner(settings: Settings) -> Planner:
    """Return the strongest planner the configuration supports."""
    if not settings.agent_llm_model.strip():
        return DeterministicPlanner()
    return AgentCorePlanner(
        AgentCorePlanModel(settings),
        max_steps=settings.agent_plan_max_steps,
    )


def _planner_prompt(agents: list[AgentDescriptor]) -> str:
    lines = [
        "You are the orchestrator of an application's agent plane.",
        "Produce an ordered plan of one or more steps for the user's request.",
        "Each step runs exactly one agent from this catalogue:",
    ]
    for agent in agents:
        capabilities = ", ".join(agent.capabilities) or "none"
        lines.append(f"- {agent.name}: {agent.description} (capabilities: {capabilities})")
    lines.extend(
        [
            "Rules:",
            "- Every step names an exact agent from the catalogue; never invent one.",
            "- Usually one step is enough; add a second step only when the request",
            "  genuinely needs another business point, because later steps see the",
            "  earlier steps' results.",
            "- Choose general only when no specialist applies, at most once.",
            "- Confidence is between 0 and 1; each reason is one sentence.",
        ]
    )
    return "\n".join(lines)
