"""Wire models for the search endpoint."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """A search request.

    ``retriever`` optionally overrides the process default for one
    call, which is how the web UI lets a user compare retrieval stages
    without restarting the app. ``top_k`` similarly overrides the
    configured default; ``mode`` picks which leg(s) run.

    ``embedder`` overrides the model used to embed the query for the
    dense leg. It must name the embedder that indexed the target
    documents; a mismatch silently loses the dense leg (vectors from
    different models are not comparable), so the UI sends the embedder
    the user chose at upload time.
    """

    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    retriever: str | None = None
    embedder: str | None = None


class HitRead(BaseModel):
    """One retrieved chunk as returned to the client."""

    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """The ranked result list plus the stage that produced it."""

    retriever: str
    mode: str
    hits: list[HitRead]
