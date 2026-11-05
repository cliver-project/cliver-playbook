"""Document / chunk queries.

Every read applies the collection access predicate. The v1 shared
knowledge base is the default scope (published, not deleted); a
governance deployment resolves a governed scope per caller, so the same
endpoints never expose a staged or over-classified document.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope, policy_for
from cliver_playbook.app.rag.models.entities import Chunk, Document


async def list_documents(db: AsyncSession, scope: AccessScope) -> list[Document]:
    """Visible documents, newest first (id breaks timestamp ties)."""
    result = await db.execute(
        select(Document)
        .where(policy_for(scope).predicate(scope))
        .order_by(Document.created_at.desc(), Document.id.asc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, document_id: str, scope: AccessScope) -> Document | None:
    """One visible document by content-hash id, or None."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            policy_for(scope).predicate(scope),
        )
    )
    return result.scalar_one_or_none()


async def list_chunks(db: AsyncSession, document_id: str, scope: AccessScope) -> list[Chunk]:
    """A visible document's chunks in ordinal order."""
    result = await db.execute(
        select(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.document_id == document_id,
            policy_for(scope).predicate(scope),
        )
        .order_by(Chunk.ordinal)
    )
    return list(result.scalars().all())
