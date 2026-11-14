"""Project-owned declarative base; autogenerate sees only project tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata for the project's own tables."""
