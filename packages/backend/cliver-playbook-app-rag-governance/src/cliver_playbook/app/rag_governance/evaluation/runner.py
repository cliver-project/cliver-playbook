"""The evaluation runner: replay each case, apply every evaluator, persist.

Time is injected once. The runner picks a frozen reference time (the
caller's, or one reading of the system clock) and gives each case its
``as_of`` when present; evaluators only ever compare against
``ctx.reference_time``. The system clock is consulted exactly once more,
for the audit timestamp on the finished run — never for a freshness
judgement.

A leak-probe case is replayed twice: first as the case's
``run_as_clearance``, then as its ``leak_probe_clearance``. Both traces
reach the evaluators, so the access evaluator judges the probe while
every other evaluator judges the primary answer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope
from cliver_playbook.app.rag_governance.evaluation.context import (
    ClaimJudge,
    EvalContext,
    Evaluator,
    Judge,
    QueryRunner,
)
from cliver_playbook.app.rag_governance.evaluation.report import CaseResult, EvalReport
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase
from cliver_playbook.app.rag_governance.golden.versions import load_cases
from cliver_playbook.app.rag_governance.models.entities import (
    GovEvalCaseResult,
    GovEvalRun,
    GovGoldenSet,
    GovProject,
)
from cliver_playbook.app.rag_governance.rules.schema import IntentRule


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class _CaseEvaluation:
    case: GoldenCase
    results: list[CaseResult]


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def _case_passed(results: Sequence[CaseResult]) -> bool:
    considered = [result for result in results if not result.skipped]
    return all(result.passed for result in considered) if considered else True


def _aggregate_metrics(results: Sequence[CaseResult]) -> dict[str, float]:
    by_evaluator: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        by_evaluator[result.evaluator].append(result)

    metrics: dict[str, float] = {}
    for evaluator_name, items in sorted(by_evaluator.items()):
        scored = [item for item in items if not item.skipped]
        if not scored:
            continue
        metrics[f"{evaluator_name}.pass_rate"] = sum(
            1.0 if item.passed else 0.0 for item in scored
        ) / len(scored)
        for key in sorted({key for item in scored for key in item.metrics}):
            values = [item.metrics[key] for item in scored if key in item.metrics]
            if values:
                metrics[f"{evaluator_name}.{key}"] = sum(values) / len(values)
    return metrics


def _hard_violations(results: Sequence[CaseResult], hard_gate_names: set[str]) -> list[str]:
    violations: list[str] = []
    for result in results:
        fatal = result.violations if result.evaluator in hard_gate_names else result.hard_violations
        violations.extend(
            f"{result.case_id}/{result.evaluator}: {violation}" for violation in fatal
        )
    return violations


def _threshold_failures(metrics: dict[str, float], thresholds: dict[str, float]) -> list[str]:
    failures: list[str] = []
    for key, raw_floor in thresholds.items():
        try:
            floor = float(raw_floor)
        except (TypeError, ValueError):
            continue
        metric_key = key if "." in key else f"{key}.pass_rate"
        value = metrics.get(metric_key)
        if value is not None and value < floor:
            failures.append(f"{metric_key}={value:.3f} is below {floor:.3f}")
    return failures


async def _observe(
    case: GoldenCase,
    ctx: EvalContext,
    query_runner: QueryRunner,
    *,
    collection_id: str,
) -> EvalContext:
    primary_ctx = replace(
        ctx,
        access=AccessScope(
            collection_id=collection_id,
            clearance=case.run_as_clearance,
            governed=True,
        ),
    )
    primary = await query_runner(case, primary_ctx)
    probe = None
    if case.leak_probe_clearance is not None:
        probe_ctx = replace(
            primary_ctx,
            access=AccessScope(
                collection_id=collection_id,
                clearance=case.leak_probe_clearance,
                governed=True,
            ),
        )
        probe = await query_runner(case, probe_ctx)
    return replace(ctx, access=primary_ctx.access, observation=primary, probe_observation=probe)


async def run_evaluation(
    db: AsyncSession,
    *,
    project: GovProject,
    golden_set: GovGoldenSet,
    rules: Iterable[IntentRule],
    evaluators: Sequence[Evaluator],
    query_runner: QueryRunner | None = None,
    reference_time: datetime | None = None,
    thresholds: dict[str, float] | None = None,
    judge: Judge | None = None,
    claim_judge: ClaimJudge | None = None,
    rule_version: int | None = None,
    stage: str = "baseline",
    actor: str = "",
    clock: Clock | None = None,
) -> EvalReport:
    """Evaluate every case in a confirmed set and persist the run."""
    resolved_clock = clock or SystemClock()
    run_reference = reference_time or resolved_clock.now()
    _require_aware(run_reference, "reference_time")

    cases = await load_cases(db, golden_set.id)
    config = dict(project.config_json or {})
    hard_gate_names = {
        evaluator.name for evaluator in evaluators if getattr(evaluator, "hard_gate", False)
    }
    evaluations: list[_CaseEvaluation] = []

    run = GovEvalRun(
        project_id=project.id,
        golden_set_id=golden_set.id,
        rule_version=rule_version,
        stage=stage,
        status="running",
        metrics_json={},
        report_json={},
        created_by=actor,
    )
    db.add(run)
    await db.flush()
    run_id = run.id
    await db.commit()

    try:
        for case in cases:
            case_reference = case.as_of or run_reference
            _require_aware(case_reference, f"case {case.id} reference_time")
            ctx = EvalContext(
                project=project,
                golden_set=golden_set,
                rules=tuple(rules),
                reference_time=case_reference,
                query_runner=query_runner,
                config=config,
                judge=judge,
                claim_judge=claim_judge,
            )
            if query_runner is not None:
                ctx = await _observe(case, ctx, query_runner, collection_id=project.collection_id)
            results = [await evaluator.evaluate(case, ctx) for evaluator in evaluators]
            evaluations.append(_CaseEvaluation(case=case, results=results))
    except Exception as exc:
        await db.rollback()
        failed = await db.get(GovEvalRun, run_id)
        if failed is not None:
            failed.status = "failed"
            failed.report_json = {"error": str(exc)}
            failed.finished_at = resolved_clock.now()
            await db.commit()
        raise

    all_results = [result for evaluation in evaluations for result in evaluation.results]
    metrics = _aggregate_metrics(all_results)
    hard_violations = _hard_violations(all_results, hard_gate_names)
    project_thresholds = config.get("thresholds")
    merged_thresholds: dict[str, float] = {}
    if isinstance(project_thresholds, dict):
        merged_thresholds.update(project_thresholds)
    merged_thresholds.update(thresholds or {})
    threshold_failures = _threshold_failures(metrics, merged_thresholds)

    status = "failed" if hard_violations or threshold_failures else "passed"
    passed_cases = sum(1 for evaluation in evaluations if _case_passed(evaluation.results))
    summary = (
        f"{passed_cases}/{len(evaluations)} cases passed; "
        f"{len(hard_violations)} hard-gate violation(s); "
        f"{len(threshold_failures)} threshold miss(es)."
    )
    report = EvalReport(
        status=status,
        metrics=metrics,
        cases=all_results,
        summary=summary,
        hard_gate_violations=hard_violations,
        threshold_failures=threshold_failures,
        run_id=run_id,
    )

    for evaluation in evaluations:
        db.add(
            GovEvalCaseResult(
                run_id=run_id,
                case_id=evaluation.case.id,
                passed=_case_passed(evaluation.results),
                details_json={"results": [{**asdict(result)} for result in evaluation.results]},
            )
        )
    run = await db.get(GovEvalRun, run_id)
    assert run is not None
    run.status = status
    run.metrics_json = metrics
    run.report_json = {
        "summary": summary,
        "hard_gate_violations": hard_violations,
        "threshold_failures": threshold_failures,
        "cases": [{**asdict(result)} for result in all_results],
    }
    run.finished_at = resolved_clock.now()
    await db.commit()
    return report
