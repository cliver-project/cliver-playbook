"""Reference product entity — replace it with the project's domain."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (Index("ix_products_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
