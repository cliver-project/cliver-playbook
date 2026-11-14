"""Fallback sub-agent for requests no business-point agent claims."""

from __future__ import annotations

from app.agents.contracts import (
    AgentContext,
    AgentIntent,
    AgentResult,
    AgentToolkit,
    AutonomyPolicy,
)
from app.agents.learning import LearningPipeline


class GeneralAgent:
    name = "general"
    description = "Fallback agent for requests that no business-point agent claims."
    capabilities = ("general.help",)
    autonomy = AutonomyPolicy(
        evaluation_metric="general.help.success",
        evaluation_threshold=0.6,
        improvement_mode="proposal",
        retention_days=30,
    )
    pipeline = LearningPipeline(autonomy)

    def can_handle(self, intent: AgentIntent) -> bool:
        return False

    def toolkit(self, context: AgentContext) -> AgentToolkit:
        return AgentToolkit(
            system_prompt=(
                "You are the general fallback agent. Answer the request "
                "directly. Do not invent business data or claim capabilities "
                "this application does not have."
            )
        )

    async def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            agent=self.name,
            message=(
                "No business-point agent claimed this request. "
                "Register a sub-agent for the business point you want to handle."
            ),
            data={"capabilities": list(self.capabilities)},
        )
