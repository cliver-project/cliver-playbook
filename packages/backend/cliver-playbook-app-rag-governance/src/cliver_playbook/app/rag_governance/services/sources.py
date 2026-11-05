"""Source registration: what raw data enters a project, and how.

``kind`` names the connector (``upload``, ``directory``, ``http``,
``mcp``); ``authority`` says what the connector's output may be used
for. A high-churn ERP endpoint is a ``snapshot`` or a ``capability``
source, not a document to re-embed on every sync — the distinction is
recorded here so the ingestion worker and the UI can tell them apart.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.models.entities import GovProject, GovSource

SOURCE_KINDS: frozenset[str] = frozenset({"upload", "directory", "http", "mcp"})
SOURCE_AUTHORITIES: frozenset[str] = frozenset({"document", "snapshot", "capability"})


class SourceValidationError(ValueError):
    """The source request names an unknown kind/authority or bad config."""


async def create_source(
    db: AsyncSession,
    project: GovProject,
    *,
    kind: str,
    config: dict[str, Any] | None = None,
    authority: str = "document",
    sync_schedule: str | None = None,
    sync_enabled: bool = False,
    max_staleness_seconds: int | None = None,
) -> GovSource:
    """Register a source on a project and commit it."""
    if kind not in SOURCE_KINDS:
        raise SourceValidationError(f"kind must be one of {sorted(SOURCE_KINDS)}")
    if authority not in SOURCE_AUTHORITIES:
        raise SourceValidationError(f"authority must be one of {sorted(SOURCE_AUTHORITIES)}")
    if max_staleness_seconds is not None and max_staleness_seconds < 0:
        raise SourceValidationError("max_staleness_seconds must be >= 0")
    if sync_schedule is not None and len(sync_schedule) > 64:
        raise SourceValidationError("sync_schedule is too long")

    source = GovSource(
        project_id=project.id,
        kind=kind,
        config_json=config or {},
        authority=authority,
        sync_schedule=sync_schedule,
        sync_enabled=sync_enabled,
        max_staleness_seconds=max_staleness_seconds,
    )
    db.add(source)
    await db.commit()
    # Server-default timestamps were not returned by the INSERT; load
    # them before the response model reads the row.
    await db.refresh(source)
    return source


async def list_sources(db: AsyncSession, project_id: str) -> list[GovSource]:
    rows = await db.execute(
        select(GovSource)
        .where(GovSource.project_id == project_id)
        .order_by(GovSource.created_at, GovSource.id)
    )
    return list(rows.scalars().all())


async def get_source(db: AsyncSession, source_id: str) -> GovSource | None:
    return await db.get(GovSource, source_id)
