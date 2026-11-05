"""Contextualization fidelity: does the context introduce facts not in the parent?

This is an LLM-judged, warning-by-default check. The runner supplies the
judge; without one the evaluator skips rather than inventing a
deterministic proxy that could hide a hallucinated context. The project
may promote the warning to a gate with
``contextualization.gate = true``.
"""

from __future__ import annotations

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase


class ContextualizationEvaluator:
    name = "contextualization-fidelity"
    hard_gate = False

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")
        if ctx.judge is None:
            return skipped_result(case.id, self.name, "no contextualization judge")
        pairs = observation.contextual_pairs
        if not pairs:
            return skipped_result(case.id, self.name, "no contextual pairs")

        verdicts = [await ctx.judge(parent, contextual) for parent, contextual in pairs]
        unfaithful = len(verdicts) - sum(verdicts)
        gate = bool(ctx.config_section("contextualization").get("gate", False))
        violations = (
            [f"{unfaithful} contextual text(s) introduce facts absent from the parent"]
            if unfaithful
            else []
        )
        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not (gate and violations),
            metrics={"fidelity": 1.0 - unfaithful / len(verdicts)},
            violations=violations,
            detail={"warnings": bool(violations and not gate)},
        )
