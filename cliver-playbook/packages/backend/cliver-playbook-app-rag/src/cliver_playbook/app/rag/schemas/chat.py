"""Wire models for the chat endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A grounded question plus optional per-call stage overrides.

    ``top_k`` bounds the retriever's candidate list; ``rerank_top_k``
    bounds the context the generator sees. Every stage name defaults to
    the configured value, and overriding one for a single call is how
    the web UI compares stage combinations without a restart.

    ``embedder`` names the model used to embed the question for the
    dense leg. It must match the embedder that indexed the target
    documents; when omitted the configured default is used.
    """

    question: str = Field(min_length=1)
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    top_k: int | None = Field(default=None, ge=1)
    rerank_top_k: int | None = Field(default=None, ge=1)
    retriever: str | None = None
    embedder: str | None = None
    reranker: str | None = None
    llm: str | None = None


class Citation(BaseModel):
    """One chunk the answer is grounded in."""

    chunk_id: str
    document_id: str
    ordinal: int
    score: float
    text_preview: str


class ChatResponse(BaseModel):
    """The generated answer, its citations, and the stages that ran."""

    answer: str
    citations: list[Citation]
    model_id: str
    hits_used: int
    no_hits: bool
    retriever: str
    # ``mode`` is what actually ran; see SearchResponse for why it can
    # differ from the requested mode.
    requested_mode: str
    mode: str
    reranker: str
    llm: str
