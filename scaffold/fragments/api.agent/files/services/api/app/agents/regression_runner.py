"""Run a golden case through the real AgentCore loop with tool isolation."""

from __future__ import annotations

import uuid

from cliver_core import Decision
from cliver_core.policy import ToolCallContext

from app.agents.contracts import AgentContext, SubAgent
from app.agents.regression import GoldenCaseRunner
from app.agents.runner import AgentCoreRunner
from app.settings import Settings


class RegressionUnavailable(RuntimeError):
    """The offline gate cannot produce a model-backed answer."""


async def _deny_unsafe_tool(context: ToolCallContext) -> Decision:
    return Decision.deny("offline regression gate allows read-only tools only")


class AgentCoreCaseRunner:
    """A ``GoldenCaseRunner`` backed by the project's configured model.

    Safe tools may run; ASK-category (mutating/unknown) tools are denied by a
    permission callback. MCP servers are disabled for the gate. A fallback to
    the deterministic business path is rejected because it would not exercise
    the candidate prompt.
    """

    def __init__(self, settings: Settings, agent: SubAgent, db) -> None:
        self.settings = settings
        self.agent = agent
        self.db = db

    async def run(self, message: str, overlay: str) -> str:
        if not self.settings.agent_llm_model.strip():
            raise RegressionUnavailable("No model is configured for the offline gate")
        context = AgentContext(
            run_id=f"gate-{uuid.uuid4().hex}",
            message=message,
            metadata={"sources": list(self.agent.autonomy.allowed_sources)},
            resources={
                "db": self.db,
                "learning_db": self.db,
                "prompt_overlay_override": overlay,
                "permission_callback": _deny_unsafe_tool,
                "mcp_servers": [],
            },
        )
        parts: list[str] = []
        result_message = ""
        saw_result = False
        async for event in AgentCoreRunner(self.settings).run(self.agent, context):
            if event.get("type") == "message.delta":
                parts.append(str(event.get("delta", "")))
            if event.get("type") != "agent.result":
                continue
            saw_result = True
            data = event.get("data") or {}
            if data.get("fallback_reason") or data.get("mode") == "deterministic":
                raise RegressionUnavailable(
                    "AgentCore fell back to the deterministic path during the gate"
                )
            result_message = str(event.get("message", ""))
        if not saw_result:
            raise RegressionUnavailable("The offline gate run produced no result")
        answer = result_message.strip() or "".join(parts).strip()
        if not answer:
            raise RegressionUnavailable("The offline gate run produced an empty answer")
        return answer


def build_regression_runner(settings: Settings, agent: SubAgent, db) -> GoldenCaseRunner | None:
    """Return a model-backed gate runner, or ``None`` when no model is set."""
    if not settings.agent_llm_model.strip():
        return None
    return AgentCoreCaseRunner(settings, agent, db)
