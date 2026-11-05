"""Versioned rule sets and the activation gate.

A rule change is always a new version: proposed sets are readable and
evaluable but can never serve a query, and activation archives the
previous active version only after the gate passes. The gate is the
evaluation run itself, not a flag someone can set: the run must exist,
belong to the project, be ``passed``, and have evaluated the project's
current confirmed golden set. Otherwise a rule change could be active
without ever having been tested against the cases that define correct
behaviour.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.models.entities import (
    GovEvalRun,
    GovGoldenSet,
    GovIntentRule,
)
from cliver_playbook.app.rag_governance.rules.compiler import compile_rule_scope
from cliver_playbook.app.rag_governance.rules.schema import IntentRule, RuleValidationError


class RuleActivationError(ValueError):
    """The requested rule version cannot become active."""


class RuleSetNotFoundError(ValueError):
    """No rule set with that version exists."""


@dataclass(frozen=True)
class RuleSetVersion:
    """A rule set snapshot, independent of the ORM session."""

    project_id: str
    version: int
    status: str
    eval_run_id: str | None
    rules: list[IntentRule]


def rule_from_row(row: GovIntentRule) -> IntentRule:
    """Rebuild the validated rule from a persisted row."""
    return IntentRule.model_validate(
        {
            "intent": row.intent,
            "description": row.description,
            "priority": row.priority,
            "classifier": row.classifier_json or {},
            "scope": row.scope_json or {},
            "retrieval": row.retrieval_json or {},
            "strategy": row.strategy,
            "tools": row.tools_json or [],
            "snapshot_fallback": row.snapshot_fallback,
            "refusal": row.refusal_json or None,
        }
    )


def _validate_rules(rules: Iterable[IntentRule]) -> list[IntentRule]:
    resolved = list(rules)
    if not resolved:
        raise RuleValidationError("a rule set must contain at least one rule")
    seen: set[str] = set()
    for rule in resolved:
        if rule.intent in seen:
            raise RuleValidationError(f"duplicate rule intent {rule.intent!r}")
        seen.add(rule.intent)
        compile_rule_scope(rule)
    return resolved


def _row(
    project_id: str,
    rule: IntentRule,
    *,
    version: int,
    status: str,
    eval_run_id: str | None,
    actor: str,
) -> GovIntentRule:
    return GovIntentRule(
        project_id=project_id,
        version=version,
        intent=rule.intent,
        description=rule.description,
        priority=rule.priority,
        classifier_json=rule.classifier.model_dump(mode="json"),
        scope_json=rule.scope,
        retrieval_json=rule.retrieval.model_dump(mode="json"),
        strategy=rule.strategy,
        tools_json=list(rule.tools),
        snapshot_fallback=rule.snapshot_fallback,
        refusal_json=rule.refusal.model_dump(mode="json") if rule.refusal else {},
        status=status,
        eval_run_id=eval_run_id,
        created_by=actor,
    )


async def _next_version(db: AsyncSession, project_id: str) -> int:
    latest = await db.scalar(
        select(func.max(GovIntentRule.version)).where(GovIntentRule.project_id == project_id)
    )
    return int(latest or 0) + 1


def _version_from_rows(rows: list[GovIntentRule]) -> RuleSetVersion:
    ordered = sorted(rows, key=lambda row: (row.priority, row.intent))
    eval_run_id = next((row.eval_run_id for row in ordered if row.eval_run_id), None)
    return RuleSetVersion(
        project_id=ordered[0].project_id,
        version=ordered[0].version,
        status=ordered[0].status,
        eval_run_id=eval_run_id,
        rules=[rule_from_row(row) for row in ordered],
    )


async def get_rule_set(db: AsyncSession, project_id: str, version: int) -> RuleSetVersion | None:
    rows = (
        (
            await db.execute(
                select(GovIntentRule)
                .where(
                    GovIntentRule.project_id == project_id,
                    GovIntentRule.version == version,
                )
                .order_by(GovIntentRule.priority, GovIntentRule.intent)
            )
        )
        .scalars()
        .all()
    )
    return _version_from_rows(list(rows)) if rows else None


async def get_rule_set_or_raise(db: AsyncSession, project_id: str, version: int) -> RuleSetVersion:
    rule_set = await get_rule_set(db, project_id, version)
    if rule_set is None:
        raise RuleSetNotFoundError(f"rule set version {version} was not found")
    return rule_set


async def list_rule_sets(db: AsyncSession, project_id: str) -> list[RuleSetVersion]:
    rows = (
        (
            await db.execute(
                select(GovIntentRule)
                .where(GovIntentRule.project_id == project_id)
                .order_by(GovIntentRule.version.desc(), GovIntentRule.priority)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[int, list[GovIntentRule]] = defaultdict(list)
    for row in rows:
        grouped[row.version].append(row)
    return [_version_from_rows(grouped[version]) for version in sorted(grouped, reverse=True)]


async def active_rule_set(db: AsyncSession, project_id: str) -> RuleSetVersion | None:
    """The active snapshot the query facade resolves, if one exists."""
    rows = (
        (
            await db.execute(
                select(GovIntentRule)
                .where(
                    GovIntentRule.project_id == project_id,
                    GovIntentRule.status == "active",
                )
                .order_by(GovIntentRule.version.desc(), GovIntentRule.priority)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    version = rows[0].version
    return _version_from_rows([row for row in rows if row.version == version])


async def create_rule_set(
    db: AsyncSession,
    project_id: str,
    rules: Iterable[IntentRule],
    *,
    actor: str = "",
) -> RuleSetVersion:
    """Persist a proposed version. It cannot serve queries until activated."""
    resolved = _validate_rules(rules)
    version = await _next_version(db, project_id)
    db.add_all(
        [
            _row(
                project_id, rule, version=version, status="proposed", eval_run_id=None, actor=actor
            )
            for rule in resolved
        ]
    )
    await db.commit()
    return RuleSetVersion(
        project_id=project_id,
        version=version,
        status="proposed",
        eval_run_id=None,
        rules=resolved,
    )


async def _require_passing_run(db: AsyncSession, project_id: str, eval_run_id: str) -> GovEvalRun:
    run = await db.get(GovEvalRun, eval_run_id)
    if run is None:
        raise RuleActivationError(f"evaluation run {eval_run_id!r} was not found")
    if run.project_id != project_id:
        raise RuleActivationError("the evaluation run belongs to another project")
    if run.status != "passed":
        raise RuleActivationError(
            f"the evaluation run is {run.status!r}; only a passing run can activate rules"
        )
    current = await db.scalar(
        select(GovGoldenSet)
        .where(
            GovGoldenSet.project_id == project_id,
            GovGoldenSet.status == "confirmed",
        )
        .order_by(GovGoldenSet.version.desc())
        .limit(1)
    )
    if current is None:
        raise RuleActivationError("the project has no confirmed golden set")
    if run.golden_set_id != current.id:
        raise RuleActivationError(
            "the evaluation run did not test the current confirmed golden set"
        )
    return run


async def activate_rule_set(
    db: AsyncSession,
    project_id: str,
    rules: Iterable[IntentRule],
    eval_run_id: str | None,
    *,
    actor: str = "",
) -> RuleSetVersion:
    """Create and activate a new rule version, gated by a passing run."""
    resolved = _validate_rules(rules)
    if not eval_run_id:
        raise RuleActivationError("activation requires a passing evaluation run")
    run = await _require_passing_run(db, project_id, eval_run_id)

    version = await _next_version(db, project_id)
    await db.execute(
        update(GovIntentRule)
        .where(
            GovIntentRule.project_id == project_id,
            GovIntentRule.status == "active",
        )
        .values(status="archived")
    )
    db.add_all(
        [
            _row(
                project_id,
                rule,
                version=version,
                status="active",
                eval_run_id=eval_run_id,
                actor=actor,
            )
            for rule in resolved
        ]
    )
    # The run now names the exact rule version it approved, so a later
    # query can be explained by the same snapshot.
    if run.rule_version is None:
        run.rule_version = version
    await db.commit()
    return RuleSetVersion(
        project_id=project_id,
        version=version,
        status="active",
        eval_run_id=eval_run_id,
        rules=resolved,
    )
