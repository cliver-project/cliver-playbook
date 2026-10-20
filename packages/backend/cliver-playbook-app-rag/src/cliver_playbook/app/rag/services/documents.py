"""Document / chunk queries.

The knowledge base is shared in v1: the spec explicitly excludes
multi-tenant isolation, so listing returns every document. A future
owner column would add a filter here without changing the routers'
shape.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Chunk, Document


async def list_documents(db: AsyncSession) -> list[Document]:
    """Every document, newest first (id breaks timestamp ties)."""
    result = await db.execute(
        select(Document).order_by(Document.created_at.desc(), Document.id.asc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, document_id: str) -> Document | None:
    """One document by content-hash id, or None."""
    return await db.get(Document, document_id)


async def list_chunks(db: AsyncSession, document_id: str) -> list[Chunk]:
    """A document's chunks in ordinal order (the order the chunker made)."""
    result = await db.execute(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)
    )
    return list(result.scalars().all())
