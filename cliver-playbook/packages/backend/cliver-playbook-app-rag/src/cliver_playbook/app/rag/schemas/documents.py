"""Wire models for the document endpoints.

`DocumentRead` mirrors the ORM row with ``from_attributes``;
`ChunkRead` is constructed explicitly because the ORM attribute is
named ``metadata_json`` (the SQL column is ``metadata``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChunkerConfigRead(BaseModel):
    """The effective chunker configuration behind a document's chunks.

    `version` is the chunker implementation version, not the document
    version. Every field is optional because rows written before the
    column existed carry an empty object.
    """

    version: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class DocumentRead(BaseModel):
    """One document row as the UI consumes it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source_uri: str | None = None
    mime_type: str
    chunker_id: str
    chunker_config: ChunkerConfigRead = Field(default_factory=ChunkerConfigRead)
    embedder_id: str
    dim: int
    version: int
    status: str
    failure_reason: str | None = None
    chunk_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentList(BaseModel):
    """List envelope (an object, not a bare array, so it can grow)."""

    items: list[DocumentRead]


class ChunkRead(BaseModel):
    """One chunk with the provenance metadata its chunker produced."""

    id: str
    ordinal: int
    text: str
    token_count: int
    metadata: dict[str, Any]
    parent_id: str | None = None


class ChunkList(BaseModel):
    """List envelope for a document's chunks."""

    items: list[ChunkRead]
