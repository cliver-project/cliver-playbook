"""Declarative base shared by every ORM model and by Alembic autogenerate."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All entities subclass this base. Alembic's `target_metadata` is `Base.metadata`."""
