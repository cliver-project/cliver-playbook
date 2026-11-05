"""Retrieval quality: recall@k, MRR and nDCG@k over expected sources.

Relevance is binary: an expected ``logical_id`` present in the observed
sources is a hit. ``locator`` narrows a case's expectation in the golden
schema but is not used to score retrieval rank here, because the
retriever returns documents, not sections.

A ``none``-strategy case never retrieves; the tool-routing evaluator
enforces the zero-call rule, so this one reports the case as skipped
instead of adding a meaningless recall of 1.0.
"""

from __future__ import annotations

import math

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _ndcg(observed: list[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, logical_id in enumerate(observed, start=1)
        if logical_id in expected
    )
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, len(expected) + 1))
    return dcg / ideal if ideal else 1.0


class RetrievalEvaluator:
    name = "retrieval"
    hard_gate = False

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")
        if case.resolved_strategy() == "none":
            return skipped_result(case.id, self.name, "none-strategy case does not retrieve")

        expected = {source.logical_id for source in case.expected_sources}
        observed = _dedupe([source.logical_id for source in observation.sources])
        hits = expected & set(observed)
        recall = len(hits) / len(expected) if expected else 1.0
        first_hit = next(
            (rank for rank, logical_id in enumerate(observed, start=1) if logical_id in expected),
            None,
        )
        mrr = 1.0 / first_hit if first_hit is not None else (1.0 if not expected else 0.0)
        missing = sorted(expected - set(observed))
        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not missing,
            metrics={"recall": recall, "mrr": mrr, "ndcg": _ndcg(observed, expected)},
            violations=(
                [f"expected source(s) missing from retrieval: {', '.join(missing)}"]
                if missing
                else []
            ),
            detail={"expected": sorted(expected), "observed": observed},
        )
