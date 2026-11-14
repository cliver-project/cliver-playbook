"""The self-enhancement loop: observe, evaluate, improve, approve, apply.

This is the reference implementation of the flywheel ADR-0027 describes. It
distills each sub-agent result into a redacted experience, scores it against
the agent's launch bar, turns sustained low scores into an evidence-backed
prompt proposal, and only changes runtime behaviour after an explicit
approval. The proposal generator is deliberately deterministic and legible;
a project replaces it with a model-based one through the same seam.

The loop is fail-open for the user's run: a database or learning failure is
logged by ``LearningPipeline`` and never turns a successful business result
into a failed run.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentContext, AgentResult, AutonomyPolicy
from app.agents.models import (
    AgentConfig,
    AgentConfigVersion,
    AgentEvaluation,
    AgentExperience,
    AgentFeedback,
    AgentImprovement,
    AgentImprovementEvent,
)
from app.agents.proposals import ProposalDraft, ProposalGenerator
from app.agents.regression import (
    GoldenCaseRunner,
    RegressionError,
    run_regression_gate,
)

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "address",
        "api_key",
        "authorization",
        "display_name",
        "email",
        "full_name",
        "mobile",
        "password",
        "passwd",
        "phone",
        "refresh_token",
        "secret",
        "ssn",
        "telephone",
        "token",
        "user_name",
        "username",
    }
)
SENSITIVE_KEY_TOKENS = (
    "address",
    "authorization",
    "display_name",
    "email",
    "full_name",
    "mobile",
    "password",
    "passwd",
    "phone",
    "secret",
    "ssn",
    "telephone",
    "token",
    "user_name",
    "username",
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PHONE = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[\s.-]?)?"
    r"(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])?"
    r"\d{3}[\s.-]\d{4}(?!\d)"
)
_LONG_NUMBER = re.compile(r"(?<!\d)\d{10,15}(?!\d)")


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
    return normalized in SENSITIVE_KEYS or any(
        token in normalized for token in SENSITIVE_KEY_TOKENS
    )


MIN_PROPOSAL_SAMPLES = 3
MAX_RECENT_EVALUATIONS = 50
MAX_PROMPT_APPEND = 2000
MAX_PROMPT_OVERLAY = 4000
DEFAULT_PROMPT_APPEND = (
    "Before answering, check the available tool results and state uncertainty "
    "explicitly. If a required fact is missing, say so instead of guessing."
)


class LearningError(Exception):
    """A review action failed with an HTTP-compatible status."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def redact_text(value: str | None) -> str:
    """Remove common identifiers from free text before it is persisted."""
    text = value or ""
    text = _EMAIL.sub("[redacted-email]", text)
    text = _SSN.sub("[redacted-ssn]", text)
    text = _PHONE.sub("[redacted-phone]", text)
    return _LONG_NUMBER.sub("[redacted-number]", text)


def session_key(value: str | None) -> str | None:
    """Keep a stable session group without persisting the raw session id."""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def redact(value: Any) -> Any:
    """Recursively redact sensitive keys and identifier-shaped strings."""
    if isinstance(value, dict):
        return {
            str(key): ("[redacted]" if _is_sensitive_key(key) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


async def observe_experience(
    db: AsyncSession,
    policy: AutonomyPolicy,
    context: AgentContext,
    result: AgentResult,
) -> AgentExperience | None:
    """Persist one source-checked, redacted experience; idempotent per step.

    Returns ``None`` when the caller declared a source outside the agent's
    allow-list. An empty allow-list means no external-source restriction.
    """
    raw_sources = context.metadata.get("sources") or ()
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    sources = sorted({str(source) for source in raw_sources})
    if policy.allowed_sources and (
        not sources or not set(sources).issubset(set(policy.allowed_sources))
    ):
        logger.info(
            "Skipping observation for %s: sources %s are not a declared subset of %s",
            result.agent,
            sources,
            policy.allowed_sources,
        )
        return None

    existing = await db.scalar(
        select(AgentExperience).where(
            AgentExperience.run_id == context.run_id,
            AgentExperience.step == context.step,
            AgentExperience.agent == result.agent,
        )
    )
    if existing is not None:
        return existing

    result_data = redact(result.data)
    if not isinstance(result_data, dict):
        result_data = {"value": result_data}
    experience = AgentExperience(
        run_id=context.run_id,
        step=context.step,
        agent=result.agent,
        user_id=context.user_id,
        session_id=session_key(context.session_id),
        message=redact_text(context.message),
        result_message=redact_text(result.message),
        result_data=result_data,
        mode=str(result_data.get("mode", "")),
        sources=sources,
    )
    db.add(experience)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await db.scalar(
            select(AgentExperience).where(
                AgentExperience.run_id == context.run_id,
                AgentExperience.step == context.step,
                AgentExperience.agent == result.agent,
            )
        )
    await db.refresh(experience)
    await _prune_experiences(db, result.agent, policy.retention_days)
    await db.refresh(experience)
    return experience


async def _prune_experiences(db: AsyncSession, agent: str, retention_days: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    await db.execute(
        delete(AgentExperience).where(
            AgentExperience.agent == agent,
            AgentExperience.created_at < cutoff,
        )
    )
    await db.commit()


async def find_experience(
    db: AsyncSession,
    *,
    run_id: str,
    agent: str,
    step: int | None = None,
) -> AgentExperience | None:
    """Find one observed result; with no step, use the agent's latest step."""
    query = select(AgentExperience).where(
        AgentExperience.run_id == run_id,
        AgentExperience.agent == agent,
    )
    if step is not None:
        query = query.where(AgentExperience.step == step)
    query = query.order_by(AgentExperience.step.desc()).limit(1)
    return await db.scalar(query)


async def _find_feedback(
    db: AsyncSession, experience_id: int, user_id: int | None
) -> AgentFeedback | None:
    query = select(AgentFeedback).where(AgentFeedback.experience_id == experience_id)
    if user_id is None:
        query = query.where(AgentFeedback.user_id.is_(None)).order_by(AgentFeedback.id.desc())
    else:
        query = query.where(AgentFeedback.user_id == user_id)
    return await db.scalar(query.limit(1))


async def _update_feedback(
    db: AsyncSession, feedback: AgentFeedback, rating: int, comment: str
) -> AgentFeedback:
    feedback.rating = rating
    feedback.comment = redact_text(comment)
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def record_feedback(
    db: AsyncSession,
    *,
    experience: AgentExperience,
    user_id: int | None,
    rating: int,
    comment: str = "",
) -> AgentFeedback:
    """Record one user outcome rating (1-5); update an existing user rating."""
    if not 1 <= rating <= 5:
        raise LearningError("rating must be between 1 and 5", 422)
    experience_id = experience.id
    run_id = experience.run_id
    agent = experience.agent
    existing = await _find_feedback(db, experience_id, user_id)
    if existing is not None:
        return await _update_feedback(db, existing, rating, comment)

    feedback = AgentFeedback(
        experience_id=experience_id,
        run_id=run_id,
        agent=agent,
        user_id=user_id,
        rating=rating,
        comment=redact_text(comment),
    )
    db.add(feedback)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent rating won the unique slot; update that row instead
        # of returning a 500.
        await db.rollback()
        existing = await _find_feedback(db, experience_id, user_id)
        if existing is None:
            raise
        return await _update_feedback(db, existing, rating, comment)
    await db.refresh(feedback)
    return feedback


async def evaluate_experience(
    db: AsyncSession,
    policy: AutonomyPolicy,
    experience: AgentExperience,
) -> AgentEvaluation:
    """Score one experience against the agent's launch bar and persist it.

    The deterministic v1 combines result completeness with explicit user
    ratings. A project can replace this with a model judge or a golden-set
    evaluator; the stored metric and evidence stay the same.
    """
    experience_id = experience.id
    agent = experience.agent
    feedback_rows = (
        await db.scalars(select(AgentFeedback).where(AgentFeedback.experience_id == experience_id))
    ).all()
    ratings = [feedback.rating for feedback in feedback_rows]
    result_data = experience.result_data or {}
    has_fallback = bool(result_data.get("fallback_reason"))
    base = 1.0 if experience.result_message.strip() and not has_fallback else 0.3

    positive = sum(1 for rating in ratings if rating >= 4)
    negative = sum(1 for rating in ratings if rating <= 2)
    if positive + negative:
        feedback_score = positive / (positive + negative)
        score = 0.5 * base + 0.5 * feedback_score
    else:
        score = base
    score = round(max(0.0, min(1.0, score)), 4)
    passed = score >= policy.evaluation_threshold
    metric = (policy.evaluation_metric or "heuristic.v1")[:100]
    details = {
        "base": base,
        "feedback_count": len(ratings),
        "positive_feedback": positive,
        "negative_feedback": negative,
        "threshold": policy.evaluation_threshold,
    }

    evaluation = await db.scalar(
        select(AgentEvaluation).where(
            AgentEvaluation.experience_id == experience_id,
            AgentEvaluation.metric == metric,
        )
    )
    if evaluation is not None:
        return await _apply_evaluation(db, evaluation, score, passed, details)

    evaluation = AgentEvaluation(
        experience_id=experience_id,
        agent=agent,
        metric=metric,
        score=score,
        passed=passed,
        details=details,
    )
    db.add(evaluation)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent feedback call inserted the same metric first.
        await db.rollback()
        evaluation = await db.scalar(
            select(AgentEvaluation).where(
                AgentEvaluation.experience_id == experience_id,
                AgentEvaluation.metric == metric,
            )
        )
        if evaluation is None:
            raise
        return await _apply_evaluation(db, evaluation, score, passed, details)
    await db.refresh(evaluation)
    return evaluation


async def _apply_evaluation(
    db: AsyncSession,
    evaluation: AgentEvaluation,
    score: float,
    passed: bool,
    details: dict,
) -> AgentEvaluation:
    evaluation.score = score
    evaluation.passed = passed
    evaluation.details = details
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


async def _proposal_evidence(
    db: AsyncSession,
    rows: list[tuple[AgentEvaluation, AgentExperience]],
) -> list[dict]:
    """Build bounded, redacted outcome evidence for a distillation model."""
    selected = rows[:8]
    experience_ids = [experience.id for _, experience in selected]
    feedback_by_experience: dict[int, list[str]] = {}
    if experience_ids:
        feedback_rows = (
            await db.scalars(
                select(AgentFeedback).where(AgentFeedback.experience_id.in_(experience_ids))
            )
        ).all()
        for feedback in feedback_rows:
            feedback_by_experience.setdefault(feedback.experience_id, []).append(feedback.comment)
    return [
        {
            "input": experience.message[:1000],
            "result": experience.result_message[:1000],
            "score": evaluation.score,
            "passed": evaluation.passed,
            "feedback": feedback_by_experience.get(experience.id, [])[:3],
        }
        for evaluation, experience in selected
    ]


async def maybe_create_proposal(
    db: AsyncSession,
    policy: AutonomyPolicy,
    agent: str,
    *,
    generator: ProposalGenerator | None = None,
) -> AgentImprovement | None:
    """Create at most one pending prompt proposal from sustained low scores.

    With a configured generator the reference loops asks a model to distill
    the recent redacted evidence into a prompt addition; every provider or
    validation failure falls back to the deterministic addition. The proposal
    still requires review and, when cases exist, the golden-set gate.
    """
    if policy.improvement_mode == "off":
        return None

    metric = (policy.evaluation_metric or "heuristic.v1")[:100]
    rows = list(
        (
            await db.execute(
                select(AgentEvaluation, AgentExperience)
                .join(
                    AgentExperience,
                    AgentEvaluation.experience_id == AgentExperience.id,
                )
                .where(
                    AgentExperience.agent == agent,
                    AgentEvaluation.metric == metric,
                )
                .order_by(AgentEvaluation.created_at.desc())
                .limit(MAX_RECENT_EVALUATIONS)
            )
        ).all()
    )
    recent = [evaluation for evaluation, _ in rows]
    if len(recent) < MIN_PROPOSAL_SAMPLES:
        return None
    pass_rate = round(sum(1 for evaluation in recent if evaluation.passed) / len(recent), 4)
    if pass_rate >= policy.evaluation_threshold:
        return None

    if await get_pending_proposal(db, agent) is not None:
        return None

    negative_feedback = (
        await db.scalar(
            select(func.count(AgentFeedback.id))
            .join(AgentExperience, AgentFeedback.experience_id == AgentExperience.id)
            .where(
                AgentExperience.agent == agent,
                AgentFeedback.rating <= 2,
            )
        )
        or 0
    )
    evidence_cases = await _proposal_evidence(db, rows) if generator is not None else []
    title = f"Improve {agent} result reliability"
    rationale = (
        f"{len(recent)} recent evaluation(s) pass at {pass_rate:.0%}, "
        f"below the {policy.evaluation_threshold:.0%} launch bar; "
        f"{negative_feedback} negative feedback item(s). Add explicit "
        "verification and uncertainty guidance, then re-evaluate the agent."
    )
    prompt_append = DEFAULT_PROMPT_APPEND
    proposal_source = "deterministic"
    fallback_reason: str | None = None
    if generator is not None:
        try:
            draft = ProposalDraft.model_validate(
                await generator.draft(
                    agent=agent,
                    metric=metric,
                    threshold=policy.evaluation_threshold,
                    evidence=evidence_cases,
                )
            )
            title = draft.title
            rationale = draft.rationale
            prompt_append = draft.prompt_append
            proposal_source = "agentcore"
        except Exception as exc:  # noqa: BLE001 — deterministic fallback
            logger.warning("Proposal distillation fell back: %s", exc)
            proposal_source = "deterministic_fallback"
            fallback_reason = f"{type(exc).__name__}: {exc}"[:500]

    proposal = AgentImprovement(
        id=uuid.uuid4().hex,
        agent=agent,
        kind="prompt",
        status="pending",
        title=title,
        rationale=rationale,
        patch={"prompt_append": prompt_append},
        evidence={
            "samples": len(recent),
            "pass_rate": pass_rate,
            "threshold": policy.evaluation_threshold,
            "negative_feedback": negative_feedback,
            "metric": metric,
            "improvement_mode": policy.improvement_mode,
            "proposal_source": proposal_source,
            "generator_fallback_reason": fallback_reason,
            "evidence_cases": len(evidence_cases),
        },
    )
    db.add(proposal)
    db.add(
        AgentImprovementEvent(
            proposal_id=proposal.id,
            action="created",
            actor_id=None,
            note=(f"Generated from {len(recent)} recent evaluation(s) via {proposal_source}."),
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    await db.refresh(proposal)
    return proposal


async def get_proposal(db: AsyncSession, proposal_id: str) -> AgentImprovement | None:
    return await db.scalar(select(AgentImprovement).where(AgentImprovement.id == proposal_id))


async def get_pending_proposal(db: AsyncSession, agent: str) -> AgentImprovement | None:
    """Return the current pending proposal, if the run loop already made one."""
    return await db.scalar(
        select(AgentImprovement).where(
            AgentImprovement.agent == agent,
            AgentImprovement.kind == "prompt",
            AgentImprovement.status == "pending",
        )
    )


async def approve_proposal(
    db: AsyncSession,
    proposal_id: str,
    actor_id: int | None,
    *,
    regression_runner: GoldenCaseRunner | None = None,
    regression_min_score: float = 0.8,
) -> tuple[AgentImprovement, bool]:
    """Approve a proposal; apply prompt proposals to the active overlay.

    When golden cases exist, a prompt proposal must first pass the offline
    gate: its candidate score may not fall below the current overlay or below
    ``regression_min_score``. Tool and policy proposals are approved for a
    human to implement in code; they are never applied by this service.
    """
    proposal = await db.scalar(
        select(AgentImprovement).where(AgentImprovement.id == proposal_id).with_for_update()
    )
    if proposal is None:
        raise LearningError("Proposal not found", 404)
    if proposal.status != "pending":
        raise LearningError(f"Proposal is already {proposal.status}", 409)

    now = datetime.now(UTC)
    applied = False
    if proposal.kind == "prompt":
        try:
            report = await run_regression_gate(
                db,
                proposal,
                runner=regression_runner,
                min_score=regression_min_score,
            )
        except RegressionError as exc:
            await db.rollback()
            raise LearningError(exc.message, exc.status_code) from exc
        if report.status in {"failed", "error"}:
            await db.commit()
            reason = report.error or (
                f"baseline={report.baseline_score:.2f} "
                f"candidate={report.candidate_score:.2f} "
                f"minimum={report.min_score:.2f}"
            )
            raise LearningError(f"Offline regression gate {report.status}: {reason}", 409)
        text = str((proposal.patch or {}).get("prompt_append", "")).strip()
        if not text:
            raise LearningError("Prompt proposal has no prompt_append", 422)
        if len(text) > MAX_PROMPT_APPEND:
            raise LearningError("Prompt proposal is too large", 422)

        config = await db.scalar(
            select(AgentConfig).where(AgentConfig.agent == proposal.agent).with_for_update()
        )
        if config is None:
            config = AgentConfig(agent=proposal.agent, prompt_overlay=text, version=1)
            db.add(config)
        else:
            overlay = (
                f"{config.prompt_overlay}\n\n{text}".strip() if config.prompt_overlay else text
            )
            if len(overlay) > MAX_PROMPT_OVERLAY:
                raise LearningError("Agent prompt overlay limit reached", 422)
            config.prompt_overlay = overlay
            config.version += 1
        db.add(
            AgentConfigVersion(
                agent=proposal.agent,
                version=config.version,
                prompt_overlay=config.prompt_overlay,
                source_proposal_id=proposal.id,
                note="Approved improvement proposal.",
                created_by=actor_id,
            )
        )
        proposal.status = "applied"
        proposal.applied_at = now
        applied = True
    else:
        proposal.status = "approved"

    proposal.reviewed_by = actor_id
    proposal.reviewed_at = now
    db.add(
        AgentImprovementEvent(
            proposal_id=proposal.id,
            action="applied" if applied else "approved",
            actor_id=actor_id,
            note="" if applied else "Manual code change required.",
        )
    )
    await db.commit()
    await db.refresh(proposal)
    return proposal, applied


async def reject_proposal(
    db: AsyncSession, proposal_id: str, *, actor_id: int | None, note: str = ""
) -> AgentImprovement:
    proposal = await db.scalar(
        select(AgentImprovement).where(AgentImprovement.id == proposal_id).with_for_update()
    )
    if proposal is None:
        raise LearningError("Proposal not found", 404)
    if proposal.status != "pending":
        raise LearningError(f"Proposal is already {proposal.status}", 409)
    proposal.status = "rejected"
    proposal.reviewed_by = actor_id
    proposal.reviewed_at = datetime.now(UTC)
    db.add(
        AgentImprovementEvent(
            proposal_id=proposal.id,
            action="rejected",
            actor_id=actor_id,
            note=redact_text(note),
        )
    )
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def list_proposals(
    db: AsyncSession, *, agent: str | None = None, status: str | None = None
) -> list[AgentImprovement]:
    query = select(AgentImprovement).order_by(AgentImprovement.created_at.desc()).limit(100)
    if agent:
        query = query.where(AgentImprovement.agent == agent)
    if status:
        query = query.where(AgentImprovement.status == status)
    return list((await db.scalars(query)).all())


async def load_prompt_overlay(db: AsyncSession | None, agent: str) -> str:
    """Return the active approved guidance for an agent, if any."""
    if db is None:
        return ""
    overlay = await db.scalar(select(AgentConfig.prompt_overlay).where(AgentConfig.agent == agent))
    return overlay or ""


class LearningPipeline:
    """The real observe → evaluate → improve loop, fail-open for the run."""

    def __init__(self, policy: AutonomyPolicy) -> None:
        self.policy = policy

    @staticmethod
    def _db(context: AgentContext) -> AsyncSession | None:
        """Learning writes use a dedicated session so tools keep their transaction."""
        return context.resources.get("learning_db") or context.resources.get("db")

    async def observe(self, context: AgentContext, result: AgentResult) -> None:
        db = self._db(context)
        if db is None:
            return
        try:
            await observe_experience(db, self.policy, context, result)
        except Exception:  # learning must not fail the run
            logger.exception("Could not observe result for %s", result.agent)

    async def evaluate(self, context: AgentContext, result: AgentResult) -> dict[str, Any]:
        db = self._db(context)
        if db is None:
            return {"status": "skipped", "reason": "no database session"}
        try:
            experience = await find_experience(
                db, run_id=context.run_id, agent=result.agent, step=context.step
            )
            if experience is None:
                return {"status": "skipped", "reason": "no observed experience"}
            experience_id = experience.id
            evaluation = await evaluate_experience(db, self.policy, experience)
        except Exception as exc:  # learning must not fail the run
            logger.exception("Could not evaluate result for %s", result.agent)
            return {"status": "error", "reason": str(exc)}
        return {
            "status": "evaluated",
            "agent": result.agent,
            "metric": evaluation.metric,
            "score": evaluation.score,
            "passed": evaluation.passed,
            "details": evaluation.details,
            "experience_id": experience_id,
        }

    async def improve(
        self, context: AgentContext, evaluation: dict[str, Any]
    ) -> dict[str, Any] | None:
        db = self._db(context)
        agent = str(evaluation.get("agent", ""))
        if db is None or not agent or self.policy.improvement_mode == "off":
            return None
        try:
            proposal = await maybe_create_proposal(
                db,
                self.policy,
                agent,
                generator=context.resources.get("proposal_generator"),
            )
        except Exception:  # learning must not fail the run
            logger.exception("Could not create a proposal for %s", agent)
            return None
        if proposal is None:
            return None
        return {
            "id": proposal.id,
            "agent": proposal.agent,
            "kind": proposal.kind,
            "status": proposal.status,
            "title": proposal.title,
            "rationale": proposal.rationale,
            "patch": proposal.patch,
            "evidence": proposal.evidence,
        }
