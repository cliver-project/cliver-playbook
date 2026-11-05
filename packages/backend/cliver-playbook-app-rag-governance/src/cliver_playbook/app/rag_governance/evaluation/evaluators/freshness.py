"""Freshness: live numbers carry an ``as_of`` and are evaluated against the
injected reference time, never the host clock.

A successful tool result older than the project's
``freshness.max_staleness_seconds`` is a violation. A failed live tool
must produce an explicit "live data unavailable" answer; substituting a
snapshot is allowed only when the rule enables it, and then the snapshot
must be labeled with its period. Every comparison uses
``ctx.reference_time``.
"""

from __future__ import annotations

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase

_DEFAULT_MAX_STALENESS_SECONDS = 86_400


class FreshnessEvaluator:
    name = "freshness"
    hard_gate = True

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")

        config = {**ctx.config_section("freshness")}
        max_staleness = int(config.get("max_staleness_seconds", _DEFAULT_MAX_STALENESS_SECONDS))
        violations: list[str] = []

        for call in observation.tool_calls:
            if call.error is not None:
                unavailable = observation.unavailability_answer or (
                    "live data unavailable" in observation.answer.lower()
                )
                if not unavailable:
                    violations.append(
                        f"failed tool {call.name!r} was not reported as live data unavailable"
                    )
                if call.is_snapshot and call.period and call.period not in observation.answer:
                    violations.append(f"snapshot from {call.period} is not labeled in the answer")
                continue

            if call.as_of is None:
                violations.append(f"tool {call.name!r} result carries no as_of")
                continue
            age = (ctx.reference_time - call.as_of).total_seconds()
            if age > max_staleness:
                violations.append(
                    f"tool {call.name!r} result is {int(age)}s old (max {max_staleness}s)"
                )
            if call.is_snapshot and call.period and call.period not in observation.answer:
                violations.append(f"snapshot from {call.period} is presented without its period")

        if case.expected_tools and not observation.tool_calls:
            violations.append("the case expects live data but no tool was called")

        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not violations,
            metrics={"freshness_violations": float(len(violations))},
            violations=violations,
            detail={"max_staleness_seconds": max_staleness},
        )
