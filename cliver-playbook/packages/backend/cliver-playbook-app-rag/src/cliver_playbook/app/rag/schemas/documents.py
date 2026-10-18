"""Wire models for the document endpoints.

`DocumentRead` mirrors the ORM row with ``from_attributes``;
`ChunkRead` is constructed explicitly because the ORM attribute is
named ``metadata_json`` (the SQL column is ``metadata``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    """One document row as the UI consumes it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source_uri: str | None = None
    mime_type: str
    chunker_id: str
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
