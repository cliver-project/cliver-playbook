"""Coordinator: plan, delegate each step, and emit the run stream.

The planner and the sub-agent runner are independent seams. A plan is an
ordered list of steps, one sub-agent per step. Consecutive steps with the same
``parallel_group`` run concurrently behind a barrier; every later group sees
all earlier results through ``context.prior_results``. Members of one parallel
group do not see each other's results.

A sub-agent can also return an explicit ``AgentHandoff``. The coordinator
validates the target, emits ``agent.handoff`` and runs the target before the
next plan step, so an agent can compose another business point directly
without asking the planner again. Handoff chains are bounded and cycle-safe;
a handoff target keeps the source plan step index so the run records stay
anchored to the step that requested it.

Every runner event is tagged with the executing agent's name and step so a
multi-agent run stays attributable in the stream.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

from app.agents.contracts import (
    AgentContext,
    AgentHandoff,
    AgentIntent,
    AgentResult,
)
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


def _event(event_type: str, **fields: Any) -> dict[str, Any]:
    """Build an unnumbered event; the public stream assigns sequence order."""
    return {"type": event_type, **fields}


@dataclass
class _StepOutcome:
    result: AgentResult | None = None
    streamed_text: bool = False
    error: BaseException | None = None


def _plan_groups(steps: tuple[AgentIntent, ...]) -> list[list[tuple[int, AgentIntent]]]:
    """Group consecutive steps that share a parallel_group."""
    groups: list[list[tuple[int, AgentIntent]]] = []
    for step, intent in enumerate(steps):
        if (
            groups
            and intent.parallel_group is not None
            and groups[-1][-1][1].parallel_group == intent.parallel_group
        ):
            groups[-1].append((step, intent))
        else:
            groups.append([(step, intent)])
    return groups


def _handoff_from(value: Any) -> AgentHandoff | None:
    if value is None:
        return None
    if isinstance(value, AgentHandoff):
        return value
    if isinstance(value, dict):
        return AgentHandoff(
            target=str(value.get("target", "")),
            reason=str(value.get("reason", "")),
            payload=dict(value.get("payload") or {}),
        )
    raise ValueError("agent.result handoff must be an object")


class Coordinator:
    def __init__(
        self,
        registry: AgentRegistry,
        *,
        planner: Planner | None = None,
        runner: AgentRunner | None = None,
        default_agent: str = "general",
        max_handoff_depth: int = 2,
    ):
        if max_handoff_depth < 0:
            raise ValueError("max_handoff_depth must not be negative")
        self.registry = registry
        self.default_agent = default_agent
        self.planner = planner or DeterministicPlanner(default_agent=default_agent)
        self.runner = runner or DeterministicRunner()
        self.max_handoff_depth = max_handoff_depth

    async def plan(self, context: AgentContext) -> PlanDecision:
        return await self.planner.plan(context, self.registry.all())

    async def stream(self, context: AgentContext) -> AsyncIterator[dict[str, Any]]:
        """Assign run id and sequence in the exact order events leave the run.

        Parallel steps build events concurrently, so sequence assignment must
        happen at this single boundary; otherwise a later-yielded event could
        carry a lower sequence than one already persisted.
        """
        emitter = _Emitter(context.run_id)
        async for event in self._stream(context):
            event_type = str(event.get("type", "agent.event"))
            fields = {
                key: value
                for key, value in event.items()
                if key not in {"type", "run_id", "sequence"}
            }
            yield emitter.emit(event_type, **fields)

    async def _stream(self, context: AgentContext) -> AsyncIterator[dict[str, Any]]:
        yield _event("run.started")
        try:
            decision = await self.plan(context)
            yield _event(
                "coordinator.plan",
                steps=[
                    {
                        "name": intent.name,
                        "confidence": intent.confidence,
                        "payload": intent.payload,
                        "parallel_group": intent.parallel_group,
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
            single_step_streamed: bool | None = None
            groups = _plan_groups(decision.steps)

            for group in groups:
                resolved: list[tuple[int, AgentIntent, Any]] = []
                for step, intent in group:
                    agent = self.registry.get(intent.name)
                    if agent is None:
                        yield _event(
                            "run.failed",
                            code="no_agent",
                            message=(f"No sub-agent registered for {intent.name!r} (step {step})"),
                        )
                        return
                    resolved.append((step, intent, agent))

                if len(group) > 1 and context.resource_scope is None:
                    yield _event(
                        "run.failed",
                        code="parallel_resources",
                        message=(
                            "Parallel steps require AgentContext.resource_scope "
                            "so each step has isolated resources."
                        ),
                    )
                    return

                outcomes = [_StepOutcome() for _ in resolved]
                if len(resolved) == 1:
                    step, intent, agent = resolved[0]
                    async for event in self._run_step(
                        agent,
                        context,
                        step=step,
                        prior_results=results,
                        parallel_group=intent.parallel_group,
                        base_sources=base_sources,
                        planner=decision.planner,
                        outcome=outcomes[0],
                    ):
                        yield event
                    single_step_streamed = outcomes[0].streamed_text
                else:
                    async for event in self._run_parallel_group(
                        resolved,
                        context,
                        prior_results=results,
                        base_sources=base_sources,
                        planner=decision.planner,
                        outcomes=outcomes,
                    ):
                        yield event
                    if any(outcome.error is not None for outcome in outcomes):
                        return

                for (step, _intent, agent), outcome in zip(resolved, outcomes):
                    result = outcome.result or AgentResult(agent=agent.name, message="")
                    results.append(result)
                    # A group barrier completes before any handoff runs, so a
                    # target sees every result from the group that requested it.
                    handoff = result.handoff
                    chain = [agent.name]
                    depth = 0
                    while handoff is not None:
                        depth += 1
                        if depth > self.max_handoff_depth:
                            yield _event(
                                "run.failed",
                                code="handoff_depth",
                                message=(
                                    "Handoff chain "
                                    + " -> ".join([*chain, handoff.target])
                                    + " exceeded max_handoff_depth="
                                    f"{self.max_handoff_depth}."
                                ),
                            )
                            return
                        if handoff.target in chain:
                            yield _event(
                                "run.failed",
                                code="handoff_cycle",
                                message=("Handoff cycle: " + " -> ".join([*chain, handoff.target])),
                            )
                            return
                        target = self.registry.get(handoff.target)
                        if target is None:
                            yield _event(
                                "run.failed",
                                code="no_agent",
                                message=(f"Handoff target {handoff.target!r} is not registered."),
                            )
                            return
                        yield _event(
                            "agent.handoff",
                            agent=result.agent,
                            target=target.name,
                            reason=handoff.reason,
                            step=step,
                            depth=depth,
                        )
                        outcome = _StepOutcome()
                        async for event in self._run_step(
                            target,
                            context,
                            step=step,
                            prior_results=results,
                            parallel_group=None,
                            base_sources=base_sources,
                            planner=decision.planner,
                            outcome=outcome,
                            reason=f"handoff:{result.agent}",
                            handoff=handoff,
                            handoff_from=result.agent,
                        ):
                            yield event
                        result = outcome.result or AgentResult(agent=target.name, message="")
                        results.append(result)
                        chain.append(target.name)
                        handoff = result.handoff

            if (
                len(decision.steps) == 1
                and len(results) == 1
                and results[0].message
                and not single_step_streamed
            ):
                yield _event(
                    "message.delta",
                    delta=results[0].message,
                    agent=results[0].agent,
                )
            yield _event("run.completed")
        except Exception as exc:  # noqa: BLE001 — the stream must fail cleanly
            yield _event("run.failed", code="agent_error", message=str(exc))

    async def _run_parallel_group(
        self,
        resolved: list[tuple[int, AgentIntent, Any]],
        context: AgentContext,
        *,
        prior_results: list[AgentResult],
        base_sources: list[str],
        planner: str,
        outcomes: list[_StepOutcome],
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one group concurrently and merge events as they arrive."""
        queue: asyncio.Queue[tuple[int, dict[str, Any] | None]] = asyncio.Queue()

        async def pump(
            index: int,
            step: int,
            intent: AgentIntent,
            agent: Any,
            outcome: _StepOutcome,
        ) -> None:
            try:
                async for event in self._run_step(
                    agent,
                    context,
                    step=step,
                    prior_results=prior_results,
                    parallel_group=intent.parallel_group,
                    base_sources=base_sources,
                    planner=planner,
                    outcome=outcome,
                ):
                    await queue.put((index, event))
            except BaseException as exc:  # noqa: BLE001 — reported after the barrier
                outcome.error = exc
            finally:
                await queue.put((index, None))

        tasks = [
            asyncio.create_task(pump(index, step, intent, agent, outcomes[index]))
            for index, (step, intent, agent) in enumerate(resolved)
        ]
        pending = len(tasks)
        try:
            while pending:
                _, event = await queue.get()
                if event is None:
                    pending -= 1
                else:
                    yield event
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        errors = [outcome.error for outcome in outcomes if outcome.error is not None]
        if errors:
            yield _event("run.failed", code="agent_error", message=str(errors[0]))

    @asynccontextmanager
    async def _step_context(
        self,
        context: AgentContext,
        *,
        step: int,
        prior_results: list[AgentResult],
    ) -> AsyncIterator[AgentContext]:
        """Copy run state and, when configured, open isolated resources."""
        metadata = dict(context.metadata)
        if context.resource_scope is None:
            yield replace(
                context,
                step=step,
                prior_results=list(prior_results),
                metadata=metadata,
            )
            return
        async with context.resource_scope() as resources:
            yield replace(
                context,
                step=step,
                prior_results=list(prior_results),
                metadata=metadata,
                resources=resources,
            )

    async def _run_step(
        self,
        agent: Any,
        base_context: AgentContext,
        *,
        step: int,
        prior_results: list[AgentResult],
        parallel_group: int | None,
        base_sources: list[str],
        planner: str,
        outcome: _StepOutcome,
        reason: str | None = None,
        handoff: AgentHandoff | None = None,
        handoff_from: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        tags: dict[str, Any] = {"step": step}
        if parallel_group is not None:
            tags["parallel_group"] = parallel_group
        async with self._step_context(
            base_context, step=step, prior_results=prior_results
        ) as context:
            context.metadata["sources"] = list(base_sources)
            if handoff is not None:
                context.metadata["handoff"] = {
                    "from": handoff_from,
                    "reason": handoff.reason,
                    "payload": dict(handoff.payload),
                }
            yield _event(
                "agent.selected",
                agent=agent.name,
                reason=reason or f"planner:{planner}",
                **tags,
            )
            yield _event("agent.delegated", agent=agent.name, **tags)
            result: AgentResult | None = None
            streamed_text = False
            async for extra in self.runner.run(agent, context):
                event_type = str(extra.get("type", "agent.event"))
                fields = {key: value for key, value in extra.items() if key != "type"}
                fields.setdefault("agent", agent.name)
                fields["step"] = step
                if parallel_group is not None:
                    fields.setdefault("parallel_group", parallel_group)
                if event_type == "agent.result":
                    result = AgentResult(
                        agent=str(fields.get("agent", agent.name)),
                        message=str(fields.get("message", "")),
                        data=dict(fields.get("data") or {}),
                        handoff=_handoff_from(fields.get("handoff")),
                    )
                if event_type == "message.delta":
                    streamed_text = True
                yield _event(event_type, **fields)
            if result is None:
                result = AgentResult(agent=agent.name, message="")
            outcome.result = result
            outcome.streamed_text = streamed_text
            try:
                await agent.pipeline.observe(context, result)
            except Exception:  # learning is advisory
                logger.exception("Pipeline observe failed for %s", agent.name)
            try:
                evaluation = await agent.pipeline.evaluate(context, result)
            except Exception as exc:  # learning is advisory
                logger.exception("Pipeline evaluate failed for %s", agent.name)
                evaluation = {"status": "error", "reason": str(exc)}
            yield _event(
                "pipeline.evaluated",
                agent=agent.name,
                evaluation=evaluation,
                **tags,
            )
            try:
                proposal = await agent.pipeline.improve(context, evaluation)
            except Exception:  # learning is advisory
                logger.exception("Pipeline improve failed for %s", agent.name)
                proposal = None
            if proposal:
                yield _event(
                    "pipeline.improvement",
                    agent=agent.name,
                    proposal=proposal,
                    **tags,
                )
