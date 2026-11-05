"""Ingest batches: creation, listing, and the staged preview.

A batch id is the pipeline run id written to every document it stages.
That single fact makes the preview and the eventual publish exact: no
"documents created around the same time" approximation, no leakage
between batches.

The staged preview is the only read path in the package that sets
``allow_staged=True``. It is permission-gated at the route by
``rag_governance:staged:read``; nothing else in the codebase may reuse
this scope without that gate.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope, policy_for
from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag_governance.models.entities import (
    GovIngestBatch,
    GovProject,
    GovSource,
)

BATCH_STATUSES: frozenset[str] = frozenset(
    {
        "queued",
        "running",
        "staged",
        "review_pending",
        "approved",
        "published",
        "rejected",
        "failed",
    }
)


class BatchValidationError(ValueError):
    """The batch request is not allowed for this project/source."""


async def create_batch(
    db: AsyncSession,
    project: GovProject,
    source: GovSource | None,
    *,
    submitted_by: str = "",
) -> GovIngestBatch:
    """Create the queued batch row. The caller enqueues the job and commits."""
    if source is not None and source.project_id != project.id:
        raise BatchValidationError("source does not belong to the project")
    batch = GovIngestBatch(
        project_id=project.id,
        source_id=source.id if source is not None else None,
        status="queued",
        submitted_by=submitted_by,
    )
    db.add(batch)
    await db.flush()
    return batch


async def list_batches(db: AsyncSession, project_id: str) -> list[GovIngestBatch]:
    rows = await db.execute(
        select(GovIngestBatch)
        .where(GovIngestBatch.project_id == project_id)
        .order_by(GovIngestBatch.created_at.desc(), GovIngestBatch.id)
    )
    return list(rows.scalars().all())


async def get_batch(db: AsyncSession, batch_id: str) -> GovIngestBatch | None:
    return await db.get(GovIngestBatch, batch_id)


async def list_staged_documents(
    db: AsyncSession, project: GovProject, batch: GovIngestBatch
) -> list[Document]:
    """The documents this batch staged, including unpublished ones.

    The governed predicate with ``allow_staged`` checks the collection
    and the soft-deleted flag but deliberately skips publication and
    classification: an approver must see everything the batch produced,
    including documents above their own clearance, or they cannot judge
    the batch. The route's ``staged:read`` gate is what makes that safe.
    """
    if batch.project_id != project.id:
        raise BatchValidationError("batch does not belong to the project")
    scope = AccessScope(
        collection_id=project.collection_id,
        governed=True,
        allow_staged=True,
    )
    rows = await db.execute(
        select(Document)
        .where(
            Document.pipeline_run_id == batch.id,
            policy_for(scope).predicate(scope),
        )
        .order_by(Document.logical_id, Document.version)
    )
    return list(rows.scalars().all())
