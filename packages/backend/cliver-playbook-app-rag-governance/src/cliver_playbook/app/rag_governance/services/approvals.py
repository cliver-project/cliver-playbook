"""Approval decisions and the publish transition.

Approval is where the governance loop's evidence becomes a publication
decision. Two kinds of finding are distinguished (R10):

- **Hard gates** — masking or access leakage, a write-tool call, stale
  live data, a failed evaluation, or a missing evaluation report. These
  block approval regardless of who asks or what they write. The batch
  stays staged until the cause is fixed.
- **Soft metric gates** — recall, groundedness or intent accuracy below
  the project's thresholds. In ``manual`` mode an approver may override
  them with a mandatory comment; the batch records the override and the
  failing metrics. ``auto`` never overrides.

Publishing itself is one transaction: every previously published row
for the same logical document in this project is unpublished first, then
this batch's rows are published. New versions never coexist with the old
one in retrieval, and the partial unique index on
``rag_documents(logical_id) WHERE published`` is the final guard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag_governance.models.entities import (
    GovApproval,
    GovEvalRun,
    GovIngestBatch,
    GovPrincipalClearance,
    GovProject,
)

Decision = Literal["approve", "reject"]

_DECISIONS: frozenset[str] = frozenset({"approve", "reject"})
_REVIEW_STATES: frozenset[str] = frozenset({"staged", "review_pending"})
_LIVE_PROJECT_STATES: frozenset[str] = frozenset({"draft", "baseline_eval"})


class ApprovalError(ValueError):
    """Base class for approval failures."""


class ApprovalValidationError(ApprovalError):
    """The decision or its comment is malformed."""


class ApprovalConflictError(ApprovalError):
    """The batch is not in a state that can be decided."""


class ApprovalBlockedError(ApprovalError):
    """A hard gate, a missing report, or a clearance check failed."""


async def _actor_clearance(db: AsyncSession, actor: str) -> int:
    """Best-effort lookup when the caller did not supply a clearance.

    API callers pass the viewer's effective clearance explicitly; this
    fallback supports workers and tests that only know a principal id.
    A missing row means level 0, matching R9.
    """
    if not actor:
        return 0
    level = await db.scalar(
        select(GovPrincipalClearance.level).where(
            GovPrincipalClearance.principal_type == "user",
            GovPrincipalClearance.principal_id == actor,
        )
    )
    return int(level or 0)


async def _evaluation_gates(
    db: AsyncSession, batch: GovIngestBatch
) -> tuple[GovEvalRun, list[str]]:
    """Return the evaluation run and any soft threshold failures.

    Raises when the report is missing, belongs to another project, did
    not finish, or recorded a hard-gate violation. A missing report is
    treated as a hard failure: approval without evidence is exactly the
    bypass the gate exists to prevent (fail-closed).
    """
    if batch.eval_run_id is None:
        raise ApprovalBlockedError(
            "the batch has no evaluation report; hard gates cannot be verified"
        )
    run = await db.get(GovEvalRun, batch.eval_run_id)
    if run is None:
        raise ApprovalBlockedError("the batch's evaluation report no longer exists")
    if run.project_id != batch.project_id:
        raise ApprovalBlockedError("the evaluation report belongs to another project")
    report = dict(run.report_json or {})
    hard = [str(item) for item in report.get("hard_gate_violations") or []]
    if hard:
        raise ApprovalBlockedError("hard gates failed: " + "; ".join(hard))
    if run.status == "failed":
        failures = [str(item) for item in report.get("threshold_failures") or []]
        if not failures:
            raise ApprovalBlockedError(
                "the evaluation run failed without a recorded threshold miss"
            )
        return run, failures
    if run.status != "passed":
        raise ApprovalBlockedError(f"the evaluation run is {run.status!r}, not passed")
    return run, []


async def _required_clearance(db: AsyncSession, batch: GovIngestBatch) -> int:
    """The maximum classification among the batch's staged documents."""
    rows = (
        (
            await db.execute(
                select(Document.classification).where(Document.pipeline_run_id == batch.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise ApprovalBlockedError("the batch staged no documents")
    if any(level is None for level in rows):
        # An unlabelled document is not publishable: retrieval would
        # fail closed and hide it anyway. Require the classifier to run.
        raise ApprovalBlockedError("a staged document has no classification")
    return max(int(level) for level in rows)


async def _publish_documents(
    db: AsyncSession, project: GovProject, batch: GovIngestBatch
) -> list[str]:
    """Flip publication flags; the caller owns the transaction commit."""
    logical_ids = list(
        (
            await db.execute(
                select(Document.logical_id)
                .where(
                    Document.pipeline_run_id == batch.id,
                    Document.logical_id.is_not(None),
                )
                .distinct()
            )
        ).scalars()
    )
    if not logical_ids:
        raise ApprovalBlockedError("the batch staged no logical documents")

    # The collection guard matters: the same logical id can exist in
    # another project, and publishing here must not touch that project.
    await db.execute(
        update(Document)
        .where(
            Document.collection_id == project.collection_id,
            Document.logical_id.in_(logical_ids),
            Document.published.is_(True),
            Document.pipeline_run_id != batch.id,
        )
        .values(published=False)
    )
    await db.execute(
        update(Document)
        .where(
            Document.pipeline_run_id == batch.id,
            Document.collection_id == project.collection_id,
            Document.logical_id.is_not(None),
        )
        .values(published=True, status="indexed")
    )
    return logical_ids


async def publish_batch(db: AsyncSession, batch: GovIngestBatch) -> None:
    """Publish exactly this batch's documents, unpublishing prior versions.

    The batch id is the pipeline run id, so the two updates are exact.
    The caller commits; an approval decision records the actor and the
    publication in the same transaction.
    """
    project = await db.get(GovProject, batch.project_id)
    if project is None:
        raise ApprovalBlockedError("the batch's project no longer exists")
    await _publish_documents(db, project, batch)
    batch.status = "published"
    if project.status in _LIVE_PROJECT_STATES:
        project.status = "active"
    await db.flush()


async def decide(
    db: AsyncSession,
    batch: GovIngestBatch,
    *,
    decision: Decision,
    actor: str,
    comment: str,
    actor_clearance: int | None = None,
) -> GovApproval:
    """Approve or reject one staged batch and commit the decision.

    ``actor_clearance`` is the caller's effective clearance, computed by
    the API from ``services.access.effective_clearance``. When omitted
    the service falls back to a user-level lookup by ``actor``.
    """
    if decision not in _DECISIONS:
        raise ApprovalValidationError(f"decision must be one of {sorted(_DECISIONS)}")
    if not actor.strip():
        raise ApprovalValidationError("an approval decision requires an actor")
    if batch.status not in _REVIEW_STATES:
        raise ApprovalConflictError(f"batch is {batch.status!r}, not awaiting review")

    project = await db.get(GovProject, batch.project_id)
    if project is None:
        raise ApprovalBlockedError("the batch's project no longer exists")

    if decision == "reject":
        if not comment.strip():
            raise ApprovalValidationError("a rejection requires a comment")
        approval = GovApproval(
            batch_id=batch.id,
            decision="reject",
            comment=comment,
            actor_id=actor,
        )
        db.add(approval)
        batch.status = "rejected"
        batch.comment = comment
        await db.commit()
        await db.refresh(approval)
        return approval

    run, threshold_failures = await _evaluation_gates(db, batch)
    override = bool(threshold_failures)
    if override:
        if project.approval_mode != "manual":
            raise ApprovalBlockedError("soft metric failures can only be overridden in manual mode")
        if not comment.strip():
            raise ApprovalValidationError("overriding soft metric failures requires a comment")

    clearance = (
        actor_clearance if actor_clearance is not None else await _actor_clearance(db, actor)
    )
    required = await _required_clearance(db, batch)
    if required > clearance:
        raise ApprovalBlockedError(
            f"the batch's maximum classification is {required}, "
            f"above the approver's clearance {clearance}"
        )

    await publish_batch(db, batch)
    batch.approved_by = actor
    batch.approved_at = datetime.now(UTC)
    batch.comment = comment
    if override:
        stats: dict[str, Any] = dict(batch.stats_json or {})
        stats["approval"] = {
            "override": True,
            "threshold_failures": threshold_failures,
            "metrics": dict(run.metrics_json or {}),
            "actor": actor,
        }
        batch.stats_json = stats

    approval = GovApproval(
        batch_id=batch.id,
        decision="approve",
        comment=comment,
        actor_id=actor,
    )
    db.add(approval)
    await db.commit()
    # Server-default timestamps are not part of the INSERT result on
    # every dialect; the API serializes them immediately after this.
    await db.refresh(batch)
    await db.refresh(approval)
    return approval


async def list_approvals(db: AsyncSession, batch_id: str) -> list[GovApproval]:
    rows = await db.execute(
        select(GovApproval)
        .where(GovApproval.batch_id == batch_id)
        .order_by(GovApproval.created_at, GovApproval.id)
    )
    return list(rows.scalars().all())
