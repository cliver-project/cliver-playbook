"""RAG tables: rag_documents, rag_chunks, rag_chunk_embeddings.

Three tables by design:

- ``rag_documents`` — one row per upload, recording which chunker and
  embedder were selected for the document. Re-uploading the same
  content upserts by content-hash id, so a document row's `version`
  bumps on re-upload rather than creating a duplicate.
- ``rag_chunks`` — one row per chunk. The chunk id is a content-hash
  of (document_id, source_version, ordinal, text), so re-indexing is
  idempotent.
- ``rag_chunk_embeddings`` — one row per embedded chunk. The embedding
  column is pgvector's VECTOR(1024) in production (the HNSW index
  sits on this table); on SQLite the type is Text() for round-trip
  in unit tests.

The same `metadata_json` JSONB column carries per-chunk stage metadata
(section_path, language, source offsets) without an ALTER for every
new chunker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cliver_playbook.app.rag.models.base import Base


class Document(Base):
    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    source_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128))
    chunker_id: Mapped[str] = mapped_column(String(64))
    embedder_id: Mapped[str] = mapped_column(String(64))
    dim: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.ordinal",
    )


class Chunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_documents.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    # Stored as JSONB on PG; on SQLite the dialect falls back to JSON
    # text. The column name is `metadata` (not `metadata_json` in the
    # schema) so the production DDL is the natural name; the
    # `metadata_json` Python attribute name was chosen to avoid
    # clashing with SQLAlchemy's DeclarativeBase.metadata class attr.
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")
    embedding: Mapped[ChunkEmbedding | None] = relationship(
        back_populates="chunk",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ChunkEmbedding(Base):
    __tablename__ = "rag_chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("rag_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # pgvector's VECTOR(1024) at runtime; the unit-test engine uses
    # Text() via the dialect fallback below. Importing pgvector here
    # would force it on every test; instead the migration creates the
    # real column and tests use the same model against SQLite where
    # pgvector's Vector type falls back to a Text-adapter at DDL time.
    # In practice the model's `embedding` is a generic Mapped[Any] so
    # the actual column type is decided at the engine level; tests get
    # a Text column, production gets a vector column.
    embedding: Mapped[Any] = mapped_column(Text)
    sparse_lexical: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    embedder_version: Mapped[str] = mapped_column(String(64))

    chunk: Mapped[Chunk] = relationship(back_populates="embedding")
