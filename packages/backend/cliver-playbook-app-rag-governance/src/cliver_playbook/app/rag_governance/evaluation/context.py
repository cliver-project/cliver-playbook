"""Shared evaluator types: the context, the runner seam and the protocol.

``EvalContext.reference_time`` is injected by the runner — the case's
``as_of`` when it has one, otherwise the run's frozen reference time.
No evaluator may call ``datetime.now()``; every freshness comparison
uses this field, which is what makes a pinned live case deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from cliver_playbook.app.rag.access import AccessScope
from cliver_playbook.app.rag_governance.evaluation.observation import QueryObservation
from cliver_playbook.app.rag_governance.evaluation.report import CaseResult
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase
from cliver_playbook.app.rag_governance.models.entities import GovGoldenSet, GovProject
from cliver_playbook.app.rag_governance.rules.schema import IntentRule


class QueryRunner(Protocol):
    """Runs one case as the access scope in ``ctx`` and returns its trace."""

    async def __call__(self, case: GoldenCase, ctx: EvalContext) -> QueryObservation: ...


class Judge(Protocol):
    """Returns True when the contextual text stays faithful to the parent."""

    async def __call__(self, parent_text: str, contextual_text: str) -> bool: ...


class ClaimJudge(Protocol):
    """Returns True when the answer text supports one expected fact."""

    async def __call__(self, claim: str, answer: str, sources: tuple[str, ...]) -> bool: ...


@dataclass(frozen=True)
class EvalContext:
    project: GovProject
    golden_set: GovGoldenSet | None
    rules: tuple[IntentRule, ...]
    reference_time: datetime
    query_runner: QueryRunner | None = None
    observation: QueryObservation | None = None
    probe_observation: QueryObservation | None = None
    access: AccessScope | None = None
    config: dict[str, Any] = field(default_factory=dict)
    judge: Judge | None = None
    claim_judge: ClaimJudge | None = None

    def config_section(self, name: str) -> dict[str, Any]:
        section = self.config.get(name)
        return section if isinstance(section, dict) else {}


class Evaluator(Protocol):
    """One deterministic check over a case and its observation."""

    name: str
    hard_gate: bool

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult: ...
