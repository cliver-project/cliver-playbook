"""ORM entities.

The scaffold ships one demo entity — `Item` — as the copy-me pattern for
regular CRUD: identity PK, sensible defaults, timezone-aware timestamps. Real
projects add their entities alongside and generate follow-up migrations.

`AppSetting` is the storage half of the runtime settings framework
(ADR-0021): one row per module-owned section, holding only the values an
administrator changed. It is not a demo — do not delete it when removing the
items slice.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cliver_playbook.app.basic.db.base import Base


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


class AppSetting(Base):
    """Persisted runtime overrides for one module-owned settings section.

    ``values`` is a flat JSON object of field name -> value; only fields the
    administrator explicitly changed are present, so a later default change in
    code still reaches untouched fields. Secrets are never stored here — the
    settings API rejects them and the loader filters them out defensively.
    """

    __tablename__ = "app_settings"

    # The section key registered by the owning package (e.g. "rag", "user").
    section: Mapped[str] = mapped_column(String(64), primary_key=True)
    # PostgreSQL JSONB in production; the SQLite variant keeps the RAG test
    # suite (which creates this table from metadata) portable.
    values: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict
    )
    # The administrator who last wrote the row; nullable so deleting a user
    # does not erase the settings history (there is no FK by design — the
    # basic package cannot depend on the identity package).
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
