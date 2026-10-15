"""ORM entities.

The scaffold ships one demo entity — `Item` — as the copy-me pattern for
regular CRUD: identity PK, sensible defaults, timezone-aware timestamps. Real
projects add their entities alongside and generate follow-up migrations.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Item(Base):
    """Demo CRUD entity — replace with real domain entities as the project grows."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
