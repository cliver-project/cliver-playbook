"""Access leakage: replay the case as the leak-probe clearance.

The probe is only meaningful when the case declares one. The runner
replays the question with ``AccessScope(clearance=leak_probe_clearance)``
and hands that observation in as ``probe_observation``; the evaluator
then asserts that forbidden logical ids and over-clearance tools never
appear anywhere in the trace. A source with a NULL classification is a
violation even at clearance 99: fail-closed means an unlabeled document
must never be returned through a governed search.
"""

from __future__ import annotations

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase


class AccessLeakEvaluator:
    name = "access-leak"
    hard_gate = True

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        if case.leak_probe_clearance is None:
            return skipped_result(case.id, self.name, "the case declares no leak probe")
        observation = ctx.probe_observation or ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no probe observation")
        probe = case.leak_probe_clearance

        violations: list[str] = []
        forbidden = set(case.forbidden_sources)
        document_citations = {
            citation.ref for citation in observation.citations if citation.kind == "document"
        }
        observed_ids = {source.logical_id for source in observation.sources} | document_citations
        leaked = sorted(forbidden & observed_ids)
        violations.extend(leaked)

        texts = observation.scanned_texts()
        for logical_id in sorted(forbidden - set(leaked)):
            if any(logical_id in text for text in texts):
                violations.append(logical_id)

        for source in observation.sources:
            if source.classification is None:
                violations.append(f"unclassified source {source.logical_id!r} was returned")
            elif source.classification > probe:
                violations.append(
                    f"source {source.logical_id!r} above probe clearance {probe} was returned"
                )

        for call in observation.tool_calls:
            if not call.authorized:
                violations.append(f"unauthorized tool {call.name!r} was called")
            if call.min_clearance is not None and call.min_clearance > probe:
                violations.append(f"tool {call.name!r} above probe clearance {probe} was bound")

        deduped = list(dict.fromkeys(violations))
        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not deduped,
            metrics={"leaks": float(len(deduped))},
            violations=deduped,
            detail={"probe_clearance": probe},
        )
