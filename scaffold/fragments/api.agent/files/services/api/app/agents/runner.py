"""Sub-agent execution seam: deterministic business path or AgentCore loop.

The coordinator depends on this protocol, not on AgentCore. When a model is
configured, a sub-agent runs as a real Re-Act loop with the tools it exposes;
message deltas and tool events are streamed as typed run events. Any failure
before the first emitted event falls back to the deterministic business
method, so a provider outage does not break a run that has a business path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from cliver_core import AgentCore, CLIverMessageChunk, ModelBindings
from cliver_core.events import (
    InferenceEvent,
    InferenceEventType,
    ToolEvent,
    ToolEventType,
)

from app.agents.contracts import AgentContext, AgentToolkit, SubAgent
from app.agents.core import (
    build_llm_binding,
    build_skill_manager,
    build_system_one_selector,
)
from app.agents.learning import load_prompt_overlay
from app.agents.mcp import select_mcp_servers
from app.settings import Settings

logger = logging.getLogger(__name__)


class CoreHandle(Protocol):
    """The slice of AgentCore the runner uses; tests supply a fake."""

    def stream(self, user_input: str, **kwargs: Any) -> AsyncIterator[CLIverMessageChunk]: ...


CoreFactory = Callable[
    [AgentContext, AgentToolkit, Settings],
    AbstractAsyncContextManager[CoreHandle],
]


class AgentRunner(Protocol):
    """One sub-agent run as a stream of typed events, ending in agent.result."""

    def run(self, agent: SubAgent, context: AgentContext) -> AsyncIterator[dict[str, Any]]: ...


class DeterministicRunner:
    """Run the sub-agent's direct business method; no model call."""

    async def run(self, agent: SubAgent, context: AgentContext) -> AsyncIterator[dict[str, Any]]:
        result = await agent.run(context)
        yield {
            "type": "agent.result",
            "agent": result.agent,
            "message": result.message,
            "data": {**result.data, "mode": "deterministic"},
        }
        for extra in result.events:
            yield dict(extra)


class AgentCoreRunner:
    """Run a sub-agent through AgentCore with its tools and skills."""

    def __init__(
        self,
        settings: Settings,
        *,
        core_factory: CoreFactory | None = None,
        fallback: AgentRunner | None = None,
    ) -> None:
        self.settings = settings
        self.core_factory = core_factory or _default_core_factory
        self.fallback = fallback or DeterministicRunner()

    async def run(self, agent: SubAgent, context: AgentContext) -> AsyncIterator[dict[str, Any]]:
        if not self.settings.agent_llm_model.strip():
            async for event in self.fallback.run(agent, context):
                yield event
            return

        emitted = False
        try:
            async for event in self._run_core(agent, context):
                emitted = True
                yield event
        except Exception as exc:
            if emitted:
                # A tool may already have run; retrying the business method
                # would repeat side effects and duplicate output.
                raise
            logger.warning("AgentCore run fell back: %s", exc)
            async for event in self.fallback.run(agent, context):
                if event["type"] == "agent.result":
                    event = {
                        **event,
                        "data": {
                            **event.get("data", {}),
                            "fallback_reason": str(exc),
                        },
                    }
                yield event

    async def _run_core(
        self, agent: SubAgent, context: AgentContext
    ) -> AsyncIterator[dict[str, Any]]:
        toolkit = agent.toolkit(context)
        toolkit.agent_name = toolkit.agent_name or agent.name
        user_input = _input_with_prior(context)
        system_prompt = toolkit.system_prompt or agent.description
        override = context.resources.get("prompt_overlay_override")
        if override is not None:
            overlay = str(override)
        else:
            overlay_db = context.resources.get("learning_db") or context.resources.get("db")
            try:
                overlay = await load_prompt_overlay(overlay_db, agent.name)
            except Exception:  # approved guidance is advisory
                logger.exception("Could not load prompt overlay for %s", agent.name)
                overlay = ""
        if overlay:
            system_prompt = f"{system_prompt}\n\nApproved guidance from feedback:\n{overlay}"
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=100)
        parts: list[str] = []
        failure: list[BaseException] = []
        failed_tool_calls: set[str] = set()

        async def on_event(event: Any) -> None:
            mapped = _map_core_event(event, failed_tool_calls)
            if mapped is not None:
                await queue.put(mapped)

        async def pump(core: CoreHandle) -> None:
            try:
                async for chunk in core.stream(
                    user_input,
                    system_prompt=system_prompt,
                    max_iterations=self.settings.agent_max_iterations,
                    run_timeout=self.settings.agent_llm_timeout,
                    tool_timeout=self.settings.agent_tool_timeout,
                    mcp_servers=select_mcp_servers(context, toolkit),
                    on_event=on_event,
                ):
                    if chunk.content:
                        parts.append(chunk.content)
                        await queue.put({"type": "message.delta", "delta": chunk.content})
                    if chunk.usage is not None:
                        await queue.put(_usage_event(chunk.usage))
            except BaseException as exc:  # noqa: BLE001 — re-raised below
                failure.append(exc)
            finally:
                await queue.put(None)

        async with self.core_factory(context, toolkit, self.settings) as core:
            task = asyncio.create_task(pump(core))
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield item
            finally:
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if failure:
            raise failure[0]
        yield {
            "type": "agent.result",
            "agent": agent.name,
            "message": "".join(parts).strip(),
            "data": {"mode": "agentcore"},
        }


def build_runner(settings: Settings) -> AgentRunner:
    """Return the strongest runner the configuration supports."""
    if not settings.agent_llm_model.strip():
        return DeterministicRunner()
    return AgentCoreRunner(settings)


def _default_core_factory(
    context: AgentContext, toolkit: AgentToolkit, settings: Settings
) -> AbstractAsyncContextManager[CoreHandle]:
    binding = build_llm_binding(settings)
    if binding is None:
        raise RuntimeError("No API-plane model is configured")
    # MCP and permissions are opt-in through run resources: a project
    # supplies "mcp_client", "mcp_servers", "permission_callback" and
    # "execution_policy". No client/callback, no MCP/mutating-tool access.
    return AgentCore.open(
        ModelBindings(llm=binding),
        builtin_tools=toolkit.tools,
        skill_manager=build_skill_manager(settings, toolkit.agent_name or None),
        mcp_client=context.resources.get("mcp_client"),
        permission_callback=context.resources.get("permission_callback"),
        execution_policy=context.resources.get("execution_policy"),
        candidate_selector=build_system_one_selector(settings),
    )


def _input_with_prior(context: AgentContext) -> str:
    """Fold earlier plan steps into this step's model input."""
    if not context.prior_results:
        return context.message
    lines = ["Earlier steps in this run:"]
    for result in context.prior_results:
        lines.append(f"- {result.agent}: {result.message}")
    lines.extend(["", "Current request:", context.message])
    return "\n".join(lines)


def _usage_event(usage: Any) -> dict[str, Any]:
    return {
        "type": "usage",
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }


def _map_core_event(event: Any, failed_tool_calls: set[str] | None = None) -> dict[str, Any] | None:
    """Translate one AgentCore event into the public run contract."""
    if isinstance(event, ToolEvent):
        if event.event is ToolEventType.START:
            return {
                "type": "tool.call",
                "tool_call_id": event.tool_call_id,
                "name": event.tool_name,
                "arguments": event.args or {},
            }
        if event.event is ToolEventType.END:
            is_error = bool(failed_tool_calls and event.tool_call_id in failed_tool_calls)
            return {
                "type": "tool.result",
                "tool_call_id": event.tool_call_id,
                "result": event.result or "",
                "is_error": is_error,
            }
        if event.event in {
            ToolEventType.ERROR,
            ToolEventType.PERMISSION_DENIED,
        }:
            if failed_tool_calls is not None:
                failed_tool_calls.add(event.tool_call_id)
            return {
                "type": "tool.result",
                "tool_call_id": event.tool_call_id,
                "result": event.error or "tool failed",
                "is_error": True,
            }
        return None
    if isinstance(event, InferenceEvent) and event.event is InferenceEventType.COMPLETED:
        usage = (event.data or {}).get("usage")
        if not isinstance(usage, dict):
            return None
        return {
            "type": "usage",
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
        }
    return None
