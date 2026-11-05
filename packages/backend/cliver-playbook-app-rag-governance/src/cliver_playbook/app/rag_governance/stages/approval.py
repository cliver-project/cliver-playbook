"""Approval policies: when a staged batch needs a human decision.

The policy answers one question — does this batch wait for a person?
It does not decide whether publishing is *allowed*: hard gates are a
separate, non-overridable check in the approval service. A policy that
returns false still cannot publish a batch whose evaluation found an
access leak.

The three modes match the design's approval interaction (R13):

- ``manual``: every batch in review is human-decided.
- ``auto``: routine batches publish once hard gates pass; a failing
  gate still stops the pipeline (there is nothing to approve).
- ``hybrid``: the first load and any rule/config change are reviewed;
  routine deltas publish after hard gates. A soft metric regression
  opens a review instead of publishing silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Batch states that are waiting for (or in the middle of) review. A
# batch that is already approved/published/rejected is no longer an
# approval question, so manual returns false for it.
_REVIEW_STATES = frozenset({"staged", "review_pending"})


@dataclass(frozen=True)
class ApprovalContext:
    """Facts the auto/hybrid policies need, computed by the caller.

    Keeping them out of the policy avoids ORM knowledge in the stage
    layer and keeps the policy a pure function: the approval service
    derives these from the batch, its eval run and the project history.
    """

    hard_gates_passed: bool = True
    is_first_batch: bool = False
    rules_changed: bool = False
    soft_regression: bool = False


def _status(batch: Any) -> str:
    return getattr(batch, "status", "") or ""


class ManualApprovalPolicy:
    name = "manual"

    def requires_approval(
        self,
        project: Any,
        batch: Any,
        *,
        context: ApprovalContext | None = None,
    ) -> bool:
        return _status(batch) in _REVIEW_STATES


class AutoApprovalPolicy:
    name = "auto"

    def requires_approval(
        self,
        project: Any,
        batch: Any,
        *,
        context: ApprovalContext | None = None,
    ) -> bool:
        ctx = context or ApprovalContext()
        # A failing hard gate is a stop, not a review request. Returning
        # true here matches the plan's wording, but the approval service
        # treats a hard-gate failure as blocked either way.
        return not ctx.hard_gates_passed


class HybridApprovalPolicy:
    name = "hybrid"

    def requires_approval(
        self,
        project: Any,
        batch: Any,
        *,
        context: ApprovalContext | None = None,
    ) -> bool:
        ctx = context or ApprovalContext()
        return (
            ctx.is_first_batch
            or ctx.rules_changed
            or ctx.soft_regression
            or not ctx.hard_gates_passed
        )
