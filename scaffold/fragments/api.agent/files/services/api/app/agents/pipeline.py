"""Self-enhancing pipeline seam.

The coordinator calls ``observe``, ``evaluate`` and ``improve`` after every
sub-agent result. The reference agents use ``LearningPipeline`` in
``app.agents.learning`` (redaction, launch-bar evaluation, proposals and
approval). ``NoopPipeline`` remains for tests and projects that explicitly opt
out of learning.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.agents.contracts import AgentContext, AgentResult


class PipelineStage(StrEnum):
    OBSERVE = "observe"
    EVALUATE = "evaluate"
    IMPROVE = "improve"


class NoopPipeline:
    """Explicit opt-out used by tests and projects with no learning policy."""

    async def observe(self, context: AgentContext, result: AgentResult) -> None:
        return None

    async def evaluate(self, context: AgentContext, result: AgentResult) -> dict[str, Any]:
        return {"status": "skipped", "reason": "no evaluation pipeline configured"}

    async def improve(
        self, context: AgentContext, evaluation: dict[str, Any]
    ) -> dict[str, Any] | None:
        return None
