"""SQLAlchemy declarative base for the rag package.

One Base per package, mirroring the basic + user + mcp pattern: keeps
the autogenerate target metadata scoped to the rag package's own
models, so other packages' tables never show up in a diff.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for the rag package's ORM models."""
