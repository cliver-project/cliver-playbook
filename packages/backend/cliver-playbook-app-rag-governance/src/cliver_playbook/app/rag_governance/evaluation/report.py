"""Evaluation results: per-case outcomes and the aggregated report.

``violations`` is the complete list a reviewer reads. ``hard_violations``
is the subset that fails the run regardless of thresholds; an evaluator
whose every check is structural sets ``hard_gate`` and leaves the subset
empty. Case-level ``passed`` is false when either list is non-empty, so
a soft metric miss still fails its case without failing the run.

Warnings (the contextualization judge by default) keep ``passed=True``
but still appear in ``violations``; that is how a warning stays visible
without blocking an approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CaseResult:
    """The outcome of one evaluator for one golden case."""

    case_id: str
    evaluator: str
    passed: bool
    metrics: dict[str, float] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    hard_violations: list[str] = field(default_factory=list)
    skipped: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def skipped_result(case_id: str, evaluator: str, reason: str) -> CaseResult:
    """A check that does not apply to this case is reported, not hidden."""
    return CaseResult(
        case_id=case_id,
        evaluator=evaluator,
        passed=True,
        skipped=True,
        detail={"reason": reason},
    )


@dataclass(frozen=True)
class EvalReport:
    """The run report an approval screen renders."""

    status: str
    metrics: dict[str, float]
    cases: list[CaseResult]
    summary: str
    hard_gate_violations: list[str] = field(default_factory=list)
    threshold_failures: list[str] = field(default_factory=list)
    run_id: str | None = None
