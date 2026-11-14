"""Coordinator: plan, delegate each step, and emit the run stream.

The planner and the sub-agent runner are independent seams. A plan is an
ordered list of steps, one sub-agent per step; each later step sees the
earlier steps' results (``context.prior_results``), which is the handoff
seam. Execution is sequential in this skeleton — parallel steps are a later
layer. Every runner event is tagged with the executing agent's name so a
multi-agent run stays attributable in the stream.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.agents.contracts import AgentContext, AgentResult
from app.agents.planner import DeterministicPlanner, PlanDecision, Planner
from app.agents.registry import AgentRegistry
from app.agents.runner import AgentRunner, DeterministicRunner

logger = logging.getLogger(__name__)


class _Emitter:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.sequence = 0

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = {
            "type": event_type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            **fields,
        }
        self.sequence += 1
        return event


class Coordinator:
    def __init__(
        self,
        registry: AgentRegistry,
        *,
        planner: Planner | None = None,
        runner: AgentRunner | None = None,
        default_agent: str = "general",
    ):
        self.registry = registry
        self.default_agent = default_agent
        self.planner = planner or DeterministicPlanner(default_agent=default_agent)
        self.runner = runner or DeterministicRunner()

    async def plan(self, context: AgentContext) -> PlanDecision:
        return await self.planner.plan(context, self.registry.all())

    async def stream(self, context: AgentContext) -> AsyncIterator[dict[str, Any]]:
        emitter = _Emitter(context.run_id)
        yield emitter.emit("run.started")
        try:
            decision = await self.plan(context)
            yield emitter.emit(
                "coordinator.plan",
                steps=[
                    {
                        "name": intent.name,
                        "confidence": intent.confidence,
                        "payload": intent.payload,
                    }
                    for intent in decision.steps
                ],
            )
            raw_sources = context.metadata.get("sources") or ()
            if isinstance(raw_sources, str):
                base_sources = [raw_sources]
            else:
                base_sources = [str(source) for source in raw_sources]
            results: list[AgentResult] = []
            for step, intent in enumerate(decision.steps):
                agent = self.registry.get(intent.name)
                if agent is None:
                    yield emitter.emit(
                        "run.failed",
                        code="no_agent",
                        message=(f"No sub-agent registered for {intent.name!r} (step {step})"),
                    )
                    return
                yield emitter.emit(
                    "agent.selected",
                    agent=agent.name,
                    reason=f"planner:{decision.planner}",
                    step=step,
                )
                yield emitter.emit("agent.delegated", agent=agent.name, step=step)
                context.step = step
                # Each step starts from the caller's declared sources; one
                # agent's data access must not leak into another's policy.
                context.metadata["sources"] = list(base_sources)
                context.prior_results = list(results)
                result: AgentResult | None = None
                streamed_text = False
                async for extra in self.runner.run(agent, context):
                    event_type = str(extra.get("type", "agent.event"))
                    fields = {key: value for key, value in extra.items() if key != "type"}
                    fields.setdefault("agent", agent.name)
                    if event_type == "agent.result":
                        result = AgentResult(
                            agent=str(fields.get("agent", agent.name)),
                            message=str(fields.get("message", "")),
                            data=dict(fields.get("data") or {}),
                        )
                    if event_type == "message.delta":
                        streamed_text = True
                    yield emitter.emit(event_type, **fields)
                if result is None:
                    result = AgentResult(agent=agent.name, message="")
                results.append(result)
                try:
                    await agent.pipeline.observe(context, result)
                except Exception:  # learning is advisory
                    logger.exception("Pipeline observe failed for %s", agent.name)
                try:
                    evaluation = await agent.pipeline.evaluate(context, result)
                except Exception as exc:  # learning is advisory
                    logger.exception("Pipeline evaluate failed for %s", agent.name)
                    evaluation = {"status": "error", "reason": str(exc)}
                yield emitter.emit("pipeline.evaluated", agent=agent.name, evaluation=evaluation)
                try:
                    proposal = await agent.pipeline.improve(context, evaluation)
                except Exception:  # learning is advisory
                    logger.exception("Pipeline improve failed for %s", agent.name)
                    proposal = None
                if proposal:
                    yield emitter.emit(
                        "pipeline.improvement",
                        agent=agent.name,
                        proposal=proposal,
                    )
                # Single-step runs keep the historical final delta; multi-step
                # runs already carry each step's text in its own events.
                if len(decision.steps) == 1 and result.message and not streamed_text:
                    yield emitter.emit("message.delta", delta=result.message, agent=agent.name)
            yield emitter.emit("run.completed")
        except Exception as exc:  # noqa: BLE001 — the stream must fail cleanly
            yield emitter.emit("run.failed", code="agent_error", message=str(exc))
