"""Golden-set versioning: candidate, confirm, fork, edit.

A confirmed set is immutable. That is the property the evaluation
history depends on: a report names a set id and version, and those
cases must still say the same thing months later. Editing a confirmed
set therefore begins with ``fork_set``, which copies the cases into the
next candidate version; ``replace_cases`` then edits the candidate.

Case ids stay stable across versions (``case-0001`` remains
``case-0001`` in version 2) because reports and review comments refer
to them. The storage key is ``(golden_set_id, id)`` for that reason.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.golden.schema import (
    GoldenCase,
    GoldenValidationError,
)
from cliver_playbook.app.rag_governance.models.entities import (
    GovGoldenCase,
    GovGoldenSet,
)

GOLDEN_SOURCES: frozenset[str] = frozenset({"llm", "manual", "import"})


class GoldenSetNotFoundError(ValueError):
    """No golden set with that id."""


class GoldenVersionError(ValueError):
    """The set is in a state that forbids the requested transition."""


def _validate_cases(cases: Iterable[GoldenCase]) -> list[GoldenCase]:
    resolved = list(cases)
    if not resolved:
        raise GoldenValidationError("a golden set must contain at least one case")
    seen: set[str] = set()
    for case in resolved:
        if case.id in seen:
            raise GoldenValidationError(f"duplicate case id {case.id!r}")
        seen.add(case.id)
    return resolved


def _case_row(golden_set_id: str, case: GoldenCase, ordinal: int) -> GovGoldenCase:
    return GovGoldenCase(
        id=case.id,
        golden_set_id=golden_set_id,
        ordinal=ordinal,
        payload_json=case.model_dump(mode="json"),
        status="candidate",
    )


async def _next_version(db: AsyncSession, project_id: str) -> int:
    latest = await db.scalar(
        select(func.max(GovGoldenSet.version)).where(GovGoldenSet.project_id == project_id)
    )
    return int(latest or 0) + 1


async def get_set(db: AsyncSession, set_id: str) -> GovGoldenSet | None:
    return await db.get(GovGoldenSet, set_id)


async def get_set_or_raise(db: AsyncSession, set_id: str) -> GovGoldenSet:
    golden_set = await get_set(db, set_id)
    if golden_set is None:
        raise GoldenSetNotFoundError(f"golden set {set_id!r} was not found")
    return golden_set


async def list_sets(db: AsyncSession, project_id: str) -> list[GovGoldenSet]:
    rows = await db.execute(
        select(GovGoldenSet)
        .where(GovGoldenSet.project_id == project_id)
        .order_by(GovGoldenSet.version.desc())
    )
    return list(rows.scalars().all())


async def load_cases(db: AsyncSession, set_id: str) -> list[GoldenCase]:
    rows = await db.execute(
        select(GovGoldenCase)
        .where(GovGoldenCase.golden_set_id == set_id)
        .order_by(GovGoldenCase.ordinal, GovGoldenCase.id)
    )
    return [GoldenCase.model_validate(row.payload_json) for row in rows.scalars().all()]


async def create_candidate_set(
    db: AsyncSession,
    project_id: str,
    cases: Iterable[GoldenCase],
    *,
    actor: str = "",
    source: str = "manual",
) -> GovGoldenSet:
    """Create the next candidate version and commit it."""
    if source not in GOLDEN_SOURCES:
        raise GoldenValidationError(f"source must be one of {sorted(GOLDEN_SOURCES)}")
    resolved = _validate_cases(cases)
    golden_set = GovGoldenSet(
        project_id=project_id,
        version=await _next_version(db, project_id),
        status="candidate",
        source=source,
        created_by=actor,
    )
    db.add(golden_set)
    await db.flush()
    db.add_all([_case_row(golden_set.id, case, ordinal) for ordinal, case in enumerate(resolved)])
    await db.commit()
    await db.refresh(golden_set)
    return golden_set


async def confirm_set(db: AsyncSession, set_id: str, *, actor: str = "") -> GovGoldenSet:
    """Freeze a candidate. Confirming an already-confirmed set is a no-op."""
    golden_set = await get_set_or_raise(db, set_id)
    if golden_set.status == "confirmed":
        return golden_set
    if golden_set.status != "candidate":
        raise GoldenVersionError(f"a {golden_set.status!r} golden set cannot be confirmed")
    case_count = await db.scalar(
        select(func.count())
        .select_from(GovGoldenCase)
        .where(GovGoldenCase.golden_set_id == golden_set.id)
    )
    if not case_count:
        raise GoldenVersionError("a golden set with no cases cannot be confirmed")

    golden_set.status = "confirmed"
    golden_set.confirmed_by = actor
    await db.execute(
        update(GovGoldenCase)
        .where(GovGoldenCase.golden_set_id == golden_set.id)
        .values(status="confirmed")
    )
    await db.commit()
    await db.refresh(golden_set)
    return golden_set


async def fork_set(db: AsyncSession, set_id: str, *, actor: str = "") -> GovGoldenSet:
    """Copy a set's cases into the next candidate version."""
    source_set = await get_set_or_raise(db, set_id)
    if source_set.status == "archived":
        raise GoldenVersionError("an archived golden set cannot be forked")
    cases = await load_cases(db, source_set.id)
    return await create_candidate_set(
        db,
        source_set.project_id,
        cases,
        actor=actor,
        source=source_set.source,
    )


def _require_editable(golden_set: GovGoldenSet) -> None:
    if golden_set.status != "candidate":
        raise GoldenVersionError(
            f"a {golden_set.status!r} golden set is immutable; fork it to edit"
        )


async def update_case(
    db: AsyncSession,
    case_id: str,
    changes: dict[str, Any],
    *,
    set_id: str | None = None,
) -> GoldenCase:
    """Patch one case in a candidate set.

    ``set_id`` disambiguates the row; without it, the newest set that
    contains the id is used. A confirmed set rejects the edit no matter
    which path selected it.
    """
    statement = (
        select(GovGoldenCase, GovGoldenSet)
        .join(GovGoldenSet, GovGoldenSet.id == GovGoldenCase.golden_set_id)
        .where(GovGoldenCase.id == case_id)
        .order_by(GovGoldenSet.version.desc())
        .limit(1)
    )
    if set_id is not None:
        statement = statement.where(GovGoldenCase.golden_set_id == set_id)
    row = (await db.execute(statement)).first()
    if row is None:
        raise GoldenSetNotFoundError(f"golden case {case_id!r} was not found")
    case_row, golden_set = row
    _require_editable(golden_set)

    if "id" in changes and changes["id"] != case_id:
        raise GoldenValidationError("a case id cannot be changed; fork instead")
    payload = {**case_row.payload_json, **changes}
    try:
        case = GoldenCase.model_validate(payload)
    except ValidationError as exc:
        raise GoldenValidationError(str(exc)) from None
    case_row.payload_json = case.model_dump(mode="json")
    await db.commit()
    return case


async def replace_cases(
    db: AsyncSession,
    set_id: str,
    cases: Iterable[GoldenCase],
    *,
    actor: str = "",
) -> GovGoldenSet:
    """Replace every case in a candidate set; the set itself is unchanged."""
    golden_set = await get_set_or_raise(db, set_id)
    _require_editable(golden_set)
    resolved = _validate_cases(cases)
    await db.execute(delete(GovGoldenCase).where(GovGoldenCase.golden_set_id == golden_set.id))
    db.add_all([_case_row(golden_set.id, case, ordinal) for ordinal, case in enumerate(resolved)])
    await db.commit()
    await db.refresh(golden_set)
    return golden_set
