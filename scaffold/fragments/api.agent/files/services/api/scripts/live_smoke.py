#!/usr/bin/env python3
"""Opt-in live smoke for the model-backed agent features.

Requires CLIVER_AGENT_LLM_MODEL, CLIVER_AGENT_LLM_BASE_URL and
CLIVER_AGENT_LLM_API_KEY in the local environment. Never run in CI and never
commit the key. Exercises chat, parallel plan execution, direct handoff, the
LLM judge, compaction and the scoped tool permission callback; MCP is
exercised when CLIVER_AGENT_MCP_ENABLED is set.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from cliver_core import AgentCore, ModelBindings, tool
from cliver_core.compaction import CompactionContext
from cliver_core.messages import CLIverMessage
from cliver_core.provider import UsageInfo

from app.agents.contracts import (
    AgentContext,
    AgentIntent,
    AgentResult,
    AgentToolkit,
    AutonomyPolicy,
)
from app.agents.coordinator import Coordinator
from app.agents.core import build_llm_binding
from app.agents.judge import build_golden_case_judge
from app.agents.mcp_runtime import close_mcp_runtime, open_mcp_runtime
from app.agents.permissions import build_permission_callback
from app.agents.pipeline import NoopPipeline
from app.agents.planner import PlanDecision, build_planner
from app.agents.registry import AgentRegistry
from app.agents.runner import build_context_compactor, build_runner
from app.settings import Settings


async def _chat(settings: Settings) -> None:
    binding = build_llm_binding(settings)
    if binding is None:
        raise SystemExit("CLIVER_AGENT_LLM_MODEL/BASE_URL/API_KEY are required")
    async with AgentCore.open(ModelBindings(llm=binding)) as core:
        response = await core.chat("Reply with exactly: LIVE_OK", max_iterations=1, run_timeout=60)
    content = response.message.content or ""
    if "LIVE_OK" not in content:
        raise SystemExit(f"chat smoke failed: {content[:120]!r}")
    print("chat: OK")


class _LiveAgent:
    """Small deterministic business point used by the orchestration smoke."""

    autonomy = AutonomyPolicy()
    pipeline = NoopPipeline()

    def __init__(self, name: str, description: str, capability: str) -> None:
        self.name = name
        self.description = description
        self.capabilities = (capability,)

    def can_handle(self, intent: AgentIntent) -> bool:
        return False

    def toolkit(self, context: AgentContext) -> AgentToolkit:
        return AgentToolkit(system_prompt=self.description)

    async def run(self, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.2)
        return AgentResult(agent=self.name, message=f"{self.name} check complete.")


class _TriageAgent(_LiveAgent):
    """AgentCore-backed agent that must use the direct handoff tool."""

    def toolkit(self, context: AgentContext) -> AgentToolkit:
        return AgentToolkit(
            system_prompt=(
                "You are the triage agent. For any refund request you must call "
                "handoff_to_agent with target 'policy' and a one-sentence reason. "
                "Do not answer the request yourself."
            ),
            handoff_targets=("policy",),
        )

    async def run(self, context: AgentContext) -> AgentResult:  # pragma: no cover
        raise AssertionError("the live smoke expects the AgentCore path")


class _FixedPlanner:
    async def plan(self, context: AgentContext, agents):
        return PlanDecision(
            steps=(AgentIntent(name="triage", confidence=1.0, payload={}),),
            planner="live-smoke",
        )


@asynccontextmanager
async def _scope():
    yield {}


async def _orchestration(settings: Settings) -> None:
    """Exercise real-model parallel planning and direct handoff."""
    binding = build_llm_binding(settings)
    if binding is None:
        raise SystemExit("orchestration smoke needs the configured model")

    registry = AgentRegistry()
    registry.register(_LiveAgent("catalog", "Look up product catalogue entries.", "catalog.lookup"))
    registry.register(_LiveAgent("policy", "Check account and refund policy.", "policy.check"))
    planner = build_planner(settings)
    messages = [
        "Check the product catalogue and the account policy in parallel. They are independent.",
        "Return two steps in parallel_group 0: catalog first, then policy. They must run concurrently.",
    ]
    decision = None
    for message in messages:
        candidate = await planner.plan(
            AgentContext(run_id="live-smoke-plan", message=message),
            registry.all(),
        )
        groups: dict[int, list[str]] = {}
        for intent in candidate.steps:
            if intent.parallel_group is not None:
                groups.setdefault(intent.parallel_group, []).append(intent.name)
        if any(len(names) == 2 for names in groups.values()):
            decision = candidate
            break
        decision = candidate
    if decision is None or not any(
        len([step for step in decision.steps if step.parallel_group == group]) > 1
        for group in {step.parallel_group for step in decision.steps}
        if group is not None
    ):
        raise SystemExit(
            "parallel plan smoke failed: "
            f"planner={decision.planner if decision else 'none'} "
            f"steps={[step.name for step in decision.steps] if decision else []}"
        )

    coordinator = Coordinator(registry, planner=_FixedParallelPlanner(decision))
    events = [
        event
        async for event in coordinator.stream(
            AgentContext(
                run_id="live-smoke-parallel",
                message="run the independent checks",
                resource_scope=_scope,
            )
        )
    ]
    selected = [event for event in events if event["type"] == "agent.selected"]
    if {event["agent"] for event in selected} != {"catalog", "policy"}:
        raise SystemExit(f"parallel execution smoke failed: selected={selected}")
    if not all(event.get("parallel_group") == 0 for event in selected):
        raise SystemExit(f"parallel execution smoke failed: groups={selected}")
    if events[-1]["type"] != "run.completed":
        raise SystemExit(f"parallel execution smoke failed: terminal={events[-1]}")
    print("parallel: OK steps=2 group=0")

    handoff_registry = AgentRegistry()
    handoff_registry.register(_TriageAgent("triage", "Route refund requests.", "triage"))
    handoff_registry.register(
        _LiveAgent("policy", "Check account and refund policy.", "policy.check")
    )
    handoff_coordinator = Coordinator(
        handoff_registry,
        planner=_FixedPlanner(),
        runner=build_runner(settings),
    )
    handoff_events = [
        event
        async for event in handoff_coordinator.stream(
            AgentContext(
                run_id="live-smoke-handoff",
                message="I need a refund for order 42.",
            )
        )
    ]
    handoff = next(
        (event for event in handoff_events if event["type"] == "agent.handoff"),
        None,
    )
    if handoff is None or handoff.get("target") != "policy":
        raise SystemExit(
            f"handoff smoke failed: types={[event['type'] for event in handoff_events]}"
        )
    if handoff_events[-1]["type"] != "run.completed":
        raise SystemExit(f"handoff smoke failed: terminal={handoff_events[-1]}")
    print(f"handoff: OK {handoff['agent']} -> {handoff['target']}")


class _FixedParallelPlanner:
    def __init__(self, decision: PlanDecision) -> None:
        self.decision = decision

    async def plan(self, context: AgentContext, agents):
        return self.decision


async def _judge(settings: Settings) -> None:
    judge = build_golden_case_judge(settings)
    if judge is None:
        print("judge: skipped (CLIVER_AGENT_JUDGE_ENABLED=false or no model)")
        return
    verdict = await judge.judge(
        agent="live-smoke",
        message="What is the price?",
        output="The price is 100 cents.",
        expected_contains=["100"],
        forbidden_contains=["free"],
    )
    print(f"judge: OK passed={verdict.passed} score={verdict.score:.2f}")


async def _compaction(settings: Settings) -> None:
    compactor = build_context_compactor(settings)
    if compactor is None:
        print("compaction: skipped (CLIVER_AGENT_COMPACTION_ENABLED=false)")
        return
    messages = [
        CLIverMessage(role="user", content="First question"),
        CLIverMessage(role="assistant", content="First answer."),
        CLIverMessage(role="user", content="Second question"),
        CLIverMessage(role="assistant", content="Second answer."),
        CLIverMessage(role="user", content="Third question"),
    ]
    context = CompactionContext(
        messages=messages,
        iteration=1,
        run_id="live-smoke-compaction",
        model=settings.agent_llm_model,
        last_usage=UsageInfo(
            input_tokens=settings.agent_compaction_threshold_tokens + 1,
            output_tokens=1,
        ),
        record_usage=lambda usage: None,
    )
    plan = await compactor(context)
    if plan is None or not plan.summary:
        raise SystemExit("compaction smoke failed: no summary plan")
    print("compaction: OK")


async def _permissions(settings: Settings) -> None:
    @tool(
        name="delete_all",
        description="Delete every record. Use only when explicitly asked.",
        safety="mutating",
    )
    def delete_all() -> list[dict]:
        return [{"deleted": True}]

    seen: list[tuple[str, str]] = []
    context = AgentContext(run_id="live-smoke-permission", message="delete all records")
    toolkit = AgentToolkit(
        system_prompt="",
        tools=[delete_all],
        permission_mode="read_only",
    )
    callback = build_permission_callback(toolkit, context)

    async def wrapped(call):
        seen.append((call.tool_name, call.category.value))
        return await callback(call)

    binding = build_llm_binding(settings)
    if binding is None:
        raise SystemExit("permission smoke needs the configured model")
    async with AgentCore.open(
        ModelBindings(llm=binding),
        builtin_tools=[delete_all],
        permission_callback=wrapped,
    ) as core:
        await core.chat(
            "Call delete_all exactly once, then report the result.",
            max_iterations=3,
            run_timeout=60,
        )
    if not seen:
        raise SystemExit("permission smoke failed: the model did not call the tool")
    if not any(name == "delete_all" for name, _ in seen):
        raise SystemExit(f"permission smoke failed: unexpected calls {seen}")
    print(f"permission: OK calls={seen}")


async def _mcp(settings: Settings) -> None:
    if not settings.agent_mcp_enabled:
        print("mcp: skipped (CLIVER_AGENT_MCP_ENABLED=false)")
        return
    runtime = await open_mcp_runtime(settings)
    if runtime is None:
        raise SystemExit("mcp smoke failed: no server started")
    try:
        tools = await runtime.client.get_tools()
        if not tools:
            raise SystemExit("mcp smoke failed: no tools discovered")
        print(f"mcp: OK servers={runtime.servers} tools={[tool.name for tool in tools]}")
    finally:
        await close_mcp_runtime(runtime)


async def main() -> int:
    settings = Settings()
    await _chat(settings)
    await _orchestration(settings)
    await _judge(settings)
    await _compaction(settings)
    await _permissions(settings)
    await _mcp(settings)
    print("live smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
