"""Golden-set offline regression gate for prompt proposals.

The gate is deliberately independent of RAG governance. It stores a small,
agent-scoped case set, runs each case against the current overlay and the
candidate overlay through a supplied runner, and records the comparison.
Approval fails closed when cases exist but no model runner is available.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    AgentConfig,
    AgentGoldenCase,
    AgentImprovement,
    AgentImprovementEvent,
    AgentRegressionRun,
)


class RegressionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GoldenCaseRunner(Protocol):
    """Run one golden prompt with an explicit overlay; return the answer."""

    async def run(self, message: str, overlay: str) -> str: ...


def _normalize(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


async def create_golden_case(
    db: AsyncSession,
    *,
    agent: str,
    name: str,
    message: str,
    expected_contains: list[str] | tuple[str, ...] = (),
    forbidden_contains: list[str] | tuple[str, ...] = (),
) -> AgentGoldenCase:
    agent = agent.strip()
    name = name.strip()
    message = message.strip()
    expected = _normalize(expected_contains)
    forbidden = _normalize(forbidden_contains)
    if not agent or not name or not message:
        raise RegressionError("agent, name and message are required", 422)
    if not expected and not forbidden:
        raise RegressionError("a golden case needs at least one assertion", 422)

    case = AgentGoldenCase(
        agent=agent,
        name=name,
        message=message,
        expected_contains=expected,
        forbidden_contains=forbidden,
        enabled=True,
    )
    db.add(case)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RegressionError("A golden case with this name already exists", 409) from exc
    await db.refresh(case)
    return case


async def list_golden_cases(db: AsyncSession, *, agent: str | None = None) -> list[AgentGoldenCase]:
    query = select(AgentGoldenCase).order_by(AgentGoldenCase.agent, AgentGoldenCase.name)
    if agent:
        query = query.where(AgentGoldenCase.agent == agent)
    return list((await db.scalars(query)).all())


async def delete_golden_case(db: AsyncSession, case_id: int) -> bool:
    case = await db.scalar(select(AgentGoldenCase).where(AgentGoldenCase.id == case_id))
    if case is None:
        return False
    await db.delete(case)
    await db.commit()
    return True


async def get_regression_run(db: AsyncSession, proposal_id: str) -> AgentRegressionRun | None:
    return await db.scalar(
        select(AgentRegressionRun).where(AgentRegressionRun.proposal_id == proposal_id)
    )


def _case_passes(output: str, case: AgentGoldenCase) -> bool:
    text = output or ""
    expected = [str(value) for value in (case.expected_contains or [])]
    forbidden = [str(value) for value in (case.forbidden_contains or [])]
    return all(value in text for value in expected) and not any(
        value in text for value in forbidden
    )


async def _base_overlay(db: AsyncSession, agent: str) -> str:
    overlay = await db.scalar(select(AgentConfig.prompt_overlay).where(AgentConfig.agent == agent))
    return overlay or ""


async def run_regression_gate(
    db: AsyncSession,
    proposal: AgentImprovement,
    *,
    runner: GoldenCaseRunner | None,
    min_score: float = 0.8,
) -> AgentRegressionRun:
    """Compare the current overlay with the proposal's candidate overlay.

    The caller owns the transaction: approval commits this report together
    with the applied config, or commits it before raising on a failed gate.
    """
    cases = list(
        (
            await db.scalars(
                select(AgentGoldenCase)
                .where(
                    AgentGoldenCase.agent == proposal.agent,
                    AgentGoldenCase.enabled.is_(True),
                )
                .order_by(AgentGoldenCase.id)
            )
        ).all()
    )
    candidate_append = str((proposal.patch or {}).get("prompt_append", "")).strip()
    base_overlay = await _base_overlay(db, proposal.agent)
    candidate_overlay = (
        f"{base_overlay}\n\n{candidate_append}".strip() if base_overlay else candidate_append
    )
    min_score = max(0.0, min(1.0, float(min_score)))

    if not cases:
        run = await _save_run(
            db,
            proposal,
            status="skipped",
            baseline_score=0.0,
            candidate_score=0.0,
            min_score=min_score,
            case_results=[],
            error="No golden cases configured.",
        )
        _audit(db, proposal, "gate_skipped", "No golden cases configured.")
        return run

    if runner is None:
        run = await _save_run(
            db,
            proposal,
            status="error",
            baseline_score=0.0,
            candidate_score=0.0,
            min_score=min_score,
            case_results=[],
            error="No offline model runner is configured.",
        )
        _audit(db, proposal, "gate_error", run.error)
        return run

    if not candidate_append:
        run = await _save_run(
            db,
            proposal,
            status="error",
            baseline_score=0.0,
            candidate_score=0.0,
            min_score=min_score,
            case_results=[],
            error="The prompt proposal has no prompt_append.",
        )
        _audit(db, proposal, "gate_error", run.error)
        return run

    case_results: list[dict] = []
    baseline_passes = 0
    candidate_passes = 0
    error = ""
    try:
        for case in cases:
            baseline_output = await runner.run(case.message, base_overlay)
            candidate_output = await runner.run(case.message, candidate_overlay)
            baseline_passed = _case_passes(str(baseline_output or ""), case)
            candidate_passed = _case_passes(str(candidate_output or ""), case)
            baseline_passes += int(baseline_passed)
            candidate_passes += int(candidate_passed)
            case_results.append(
                {
                    "case_id": case.id,
                    "name": case.name,
                    "baseline_passed": baseline_passed,
                    "candidate_passed": candidate_passed,
                }
            )
    except Exception as exc:  # noqa: BLE001 — the report records the failure
        error = f"{type(exc).__name__}: {exc}"

    total = len(cases)
    baseline_score = round(baseline_passes / total, 4) if total else 0.0
    candidate_score = round(candidate_passes / total, 4) if total else 0.0
    if error:
        status = "error"
    elif candidate_score >= baseline_score and candidate_score >= min_score:
        status = "passed"
    else:
        status = "failed"

    run = await _save_run(
        db,
        proposal,
        status=status,
        baseline_score=baseline_score,
        candidate_score=candidate_score,
        min_score=min_score,
        case_results=case_results,
        error=error,
    )
    action = {"passed": "gate_passed", "failed": "gate_failed"}.get(status, "gate_error")
    _audit(
        db,
        proposal,
        action,
        f"baseline={baseline_score:.2f} candidate={candidate_score:.2f} minimum={min_score:.2f}",
    )
    return run


async def _save_run(
    db: AsyncSession,
    proposal: AgentImprovement,
    *,
    status: str,
    baseline_score: float,
    candidate_score: float,
    min_score: float,
    case_results: list[dict],
    error: str,
) -> AgentRegressionRun:
    run = await get_regression_run(db, proposal.id)
    if run is None:
        run = AgentRegressionRun(
            proposal_id=proposal.id,
            agent=proposal.agent,
            status=status,
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            min_score=min_score,
            case_results=case_results,
            error=error,
        )
        db.add(run)
    else:
        run.status = status
        run.baseline_score = baseline_score
        run.candidate_score = candidate_score
        run.min_score = min_score
        run.case_results = case_results
        run.error = error
    await db.flush()
    return run


def _audit(db: AsyncSession, proposal: AgentImprovement, action: str, note: str) -> None:
    db.add(
        AgentImprovementEvent(
            proposal_id=proposal.id,
            action=action,
            actor_id=None,
            note=note,
        )
    )
