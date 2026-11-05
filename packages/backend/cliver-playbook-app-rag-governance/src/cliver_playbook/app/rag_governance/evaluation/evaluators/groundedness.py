"""Groundedness: citations resolve and expected numbers appear in the answer.

The deterministic half is the numeric-fact check. Each number in
``expected_answer_facts`` must appear in the answer within the case's
``numeric_tolerance`` (relative, default 0.5%). That catches the failure
that matters in the finance scenario: a figure that is wrong by a
rounding unit, a decimal place or a currency unit.

Citations must resolve to a retrieved document or an observed tool call;
an invented citation is a violation whether or not its text is right.
Non-numeric facts are only judged when the project enables the LLM judge
and the runner supplies one — the default is deterministic.
"""

from __future__ import annotations

import re

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in _NUMBER.finditer(text):
        token = match.group().rstrip("%").replace(",", "")
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _matches_number(expected: float, observed: float, tolerance: float) -> bool:
    scale = max(abs(expected), abs(observed), 1e-9)
    return abs(expected - observed) <= tolerance * scale + 1e-12


class GroundednessEvaluator:
    name = "groundedness"
    hard_gate = False

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")

        violations: list[str] = []
        source_ids = {source.logical_id for source in observation.sources}
        tool_names = {call.name for call in observation.tool_calls}
        valid_citations = 0
        for citation in observation.citations:
            if citation.kind == "document":
                known = citation.ref in source_ids or citation.ref in {
                    source.logical_id for source in case.expected_sources
                }
            elif citation.kind == "tool":
                known = citation.ref in tool_names
            else:
                known = False
            if known:
                valid_citations += 1
            else:
                violations.append(f"citation {citation.kind}:{citation.ref!r} does not resolve")
        citation_validity = (
            valid_citations / len(observation.citations) if observation.citations else 1.0
        )
        if case.expected_sources and not observation.citations:
            violations.append("the answer cites no source")
            citation_validity = 0.0

        answer_numbers = _numbers(observation.answer)
        expected_numbers = [
            number for fact in case.expected_answer_facts for number in _numbers(fact)
        ]
        matched_numbers = sum(
            1
            for expected in expected_numbers
            if any(
                _matches_number(expected, observed, case.numeric_tolerance)
                for observed in answer_numbers
            )
        )
        for fact in case.expected_answer_facts:
            for expected in _numbers(fact):
                if not any(
                    _matches_number(expected, observed, case.numeric_tolerance)
                    for observed in answer_numbers
                ):
                    violations.append(
                        f"expected number {expected:g} from {fact!r} is missing from the answer"
                    )

        numeric_score = matched_numbers / len(expected_numbers) if expected_numbers else 1.0
        metrics = {
            "citation_validity": citation_validity,
            "numeric_facts": numeric_score,
        }

        config = ctx.config_section("groundedness")
        non_numeric_facts = [fact for fact in case.expected_answer_facts if not _numbers(fact)]
        if config.get("llm_judge") and ctx.claim_judge is not None and non_numeric_facts:
            source_texts = tuple(source.text for source in observation.sources if source.text)
            supported = [
                await ctx.claim_judge(fact, observation.answer, source_texts)
                for fact in non_numeric_facts
            ]
            metrics["claim_support"] = sum(supported) / len(supported)
            for fact, ok in zip(non_numeric_facts, supported, strict=True):
                if not ok:
                    violations.append(f"the answer does not support the fact {fact!r}")

        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not violations,
            metrics=metrics,
            violations=violations,
            detail={"expected_numbers": expected_numbers, "answer_numbers": answer_numbers},
        )
