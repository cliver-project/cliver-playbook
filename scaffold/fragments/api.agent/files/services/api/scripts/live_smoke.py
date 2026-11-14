#!/usr/bin/env python3
"""Opt-in live smoke for the model-backed agent features.

Requires CLIVER_AGENT_LLM_MODEL, CLIVER_AGENT_LLM_BASE_URL and
CLIVER_AGENT_LLM_API_KEY in the local environment. Never run in CI and never
commit the key. Exercises chat, the LLM judge, compaction and the scoped tool
permission callback; MCP is exercised when CLIVER_AGENT_MCP_ENABLED is set.
"""

from __future__ import annotations

import asyncio
import sys

from cliver_core import AgentCore, ModelBindings, tool
from cliver_core.compaction import CompactionContext
from cliver_core.messages import CLIverMessage
from cliver_core.provider import UsageInfo

from app.agents.contracts import AgentContext, AgentToolkit
from app.agents.core import build_llm_binding
from app.agents.judge import build_golden_case_judge
from app.agents.mcp_runtime import close_mcp_runtime, open_mcp_runtime
from app.agents.permissions import build_permission_callback
from app.agents.runner import build_context_compactor
from app.settings import Settings


async def _chat(settings: Settings) -> None:
    binding = build_llm_binding(settings)
    if binding is None:
        raise SystemExit("CLIVER_AGENT_LLM_MODEL/BASE_URL/API_KEY are required")
    async with AgentCore.open(ModelBindings(llm=binding)) as core:
        response = await core.chat(
            "Reply with exactly: LIVE_OK", max_iterations=1, run_timeout=60
        )
    content = response.message.content or ""
    if "LIVE_OK" not in content:
        raise SystemExit(f"chat smoke failed: {content[:120]!r}")
    print("chat: OK")


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
    await _judge(settings)
    await _compaction(settings)
    await _permissions(settings)
    await _mcp(settings)
    print("live smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
