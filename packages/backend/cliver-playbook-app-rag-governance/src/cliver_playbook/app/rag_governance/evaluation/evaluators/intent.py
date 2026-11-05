"""Intent accuracy: did classification choose the expected intent?"""

from __future__ import annotations

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase


class IntentEvaluator:
    name = "intent"
    hard_gate = False

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")
        passed = observation.intent == case.expected_intent
        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=passed,
            metrics={"accuracy": 1.0 if passed else 0.0},
            violations=(
                []
                if passed
                else [
                    (f"expected intent {case.expected_intent!r}, observed {observation.intent!r}")
                ]
            ),
            detail={"observed_intent": observation.intent},
        )
