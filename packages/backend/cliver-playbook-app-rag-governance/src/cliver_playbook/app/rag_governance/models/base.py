"""SQLAlchemy declarative base for the ``rag_governance`` package.

One Base per package, mirroring the basic + user + rag pattern: the
governance chain owns only the ``gov_*`` tables, so autogenerate never
diffs another package's schema. The RAG tables stay owned by ``rag``;
governance refers to them by value (``collection_id``, ``logical_id``)
rather than by foreign key, because the rag schema must remain usable
without governance installed.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class GovernanceBase(DeclarativeBase):
    """Declarative base for the governance package's ORM models."""
