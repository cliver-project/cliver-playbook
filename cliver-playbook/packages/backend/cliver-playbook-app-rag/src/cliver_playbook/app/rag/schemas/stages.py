"""Wire models for stage discovery.

The web UI builds its stage selectors from this catalog instead of
hardcoding option lists, so a newly registered chunker / embedder /
retriever / reranker / LLM appears in the UI with no frontend change.
"""

from __future__ import annotations

from pydantic import BaseModel


class StageOption(BaseModel):
    """One registered implementation of a stage."""

    name: str
    model_id: str | None = None
    version: str | None = None
    dim: int | None = None


class StageDefaults(BaseModel):
    """The configured default implementation per stage."""

    chunker: str
    embedder: str
    retriever: str
    reranker: str
    llm: str


class StageCatalog(BaseModel):
    """Every registered implementation, grouped by stage, plus defaults."""

    chunkers: list[StageOption]
    embedders: list[StageOption]
    retrievers: list[StageOption]
    rerankers: list[StageOption]
    llms: list[StageOption]
    defaults: StageDefaults
