"""RAG tables: rag_documents, rag_chunks, rag_chunk_embeddings.

Three tables by design:

- ``rag_documents`` — one row per upload, recording which chunker and
  embedder were selected for the document, plus the chunker
  configuration that produced the current chunks. Re-uploading the same
  content upserts by content-hash id, so a document row's `version`
  bumps on re-upload rather than creating a duplicate.
- ``rag_chunks`` — one row per chunk. The chunk id is a content-hash
  of (document_id, source_version, ordinal, text), so re-indexing is
  idempotent.
- ``rag_chunk_embeddings`` — one row per embedded chunk. The embedding
  column is pgvector's ``VECTOR`` (deliberately unconstrained: the
  embedder is a per-document choice, so the stub's 64-d vectors and
  BGE-M3's 1024-d vectors share the table; each row records its
  ``dim``). The ``Vector`` type stringifies on write and parses on
  read, so the same ORM model round-trips through SQLite unit tests.

The same `metadata_json` JSONB column carries per-chunk stage metadata
(section_path, language, source offsets) without an ALTER for every
new chunker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
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
    # The effective chunker configuration that produced the current
    # chunks: implementation version, size/overlap and validated options.
    # A JSONB column avoids a migration for every new chunker option and
    # is replaced atomically together with the chunks on re-upload. It is
    # 1:1 with the row and never queried independently, so a separate
    # table would add a join without enforcing any new invariant.
    chunker_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    embedder_id: Mapped[str] = mapped_column(String(64))
    dim: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    # Governance lineage. A plain upload leaves these NULL and keeps the
    # v1 behaviour; a governance pipeline sets a stable logical id, the
    # collection (project) it belongs to, its classification level, and
    # the pipeline run that produced it. `published=false` is the
    # staging flag that isolates an unapproved version from retrieval.
    logical_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    classification: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    collection_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    pipeline_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.ordinal",
    )


class ChunkParent(Base):
    """An original parent section, kept verbatim for generation.

    Children carry a short contextualised ``search_text`` for retrieval;
    the generator is given the parent this row holds, not the child and
    not an LLM summary. That is the small-to-big contract: the vector
    index searches a compact representation while the answer stays
    grounded in the source text.
    """

    __tablename__ = "rag_chunk_parents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_documents.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # The retrieval representation: an LLM-generated/contextual prefix
    # plus the child text. It is deliberately separate from ``text`` so
    # the generator can still receive the original parent.
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer)
    # Stored as JSONB on PG; on SQLite the dialect falls back to JSON
    # text. The column name is `metadata` (not `metadata_json` in the
    # schema) so the production DDL is the natural name; the
    # `metadata_json` Python attribute name was chosen to avoid
    # clashing with SQLAlchemy's DeclarativeBase.metadata class attr.
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    # The parent section this child belongs to. Null for the legacy
    # fixed-size chunkers, which have no parent representation.
    parent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("rag_chunk_parents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
    )


class ChunkEmbedding(Base):
    __tablename__ = "rag_chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("rag_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # One chunk may be embedded by more than one model over its life
    # (a project pins one embedding model, but a model migration
    # re-embeds without deleting the old vectors first). The pair is
    # the key, so re-indexing the same model is an upsert.
    embedder_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    # pgvector's `Vector` without a fixed dimension: the column holds
    # vectors from whichever embedder the document selected. The
    # per-row `dim` column records the dimension and lets the HNSW
    # expression index (see the migration) cover only the production
    # default dimension. The type serializes to pgvector's text form
    # on any dialect, so in-memory SQLite tests round-trip.
    embedding: Mapped[list[float]] = mapped_column(Vector())
    dim: Mapped[int] = mapped_column(Integer)
    sparse_lexical: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    chunk: Mapped[Chunk] = relationship(back_populates="embeddings")
