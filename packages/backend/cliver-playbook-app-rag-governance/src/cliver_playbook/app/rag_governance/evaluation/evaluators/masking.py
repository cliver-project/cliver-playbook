"""Masking leakage: the configured sensitive patterns must not survive in
any stored or returned text.

The evaluator shares the masker's compiled patterns, so it cannot drift
from what ingestion actually removes. It scans search text, chunk and
parent text (supplied as ``contexts``), tool arguments and results, and
the final answer.
"""

from __future__ import annotations

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase
from cliver_playbook.app.rag_governance.stages.masker import compiled_patterns


class MaskingLeakEvaluator:
    name = "masking-leak"
    hard_gate = True

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")

        config = ctx.config_section("masking")
        patterns = compiled_patterns(config.get("patterns"))
        hits: dict[str, int] = {}
        for text in observation.scanned_texts():
            for name, pattern in patterns.items():
                count = len(pattern.findall(text))
                if count:
                    hits[name] = hits.get(name, 0) + count

        violations = [
            f"sensitive pattern {name!r} appears {count} time(s)"
            for name, count in sorted(hits.items())
        ]
        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not violations,
            metrics={"leaks": float(sum(hits.values()))},
            violations=violations,
            detail={"counts": hits},
        )
