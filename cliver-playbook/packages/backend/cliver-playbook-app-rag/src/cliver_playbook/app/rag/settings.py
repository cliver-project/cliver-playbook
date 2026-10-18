"""Application settings for the ``rag`` package.

Extends ``user.Settings`` (identity, OIDC registry, OAuth 2.1 provider)
with the single ``rag`` block: which chunker / embedder / retriever /
reranker / LLM the composed app uses by name, the chunk-size defaults,
the search top-k, and the score floor. The full layered resolution
documented in ``basic.settings`` applies unchanged — ``rag`` keys in
``app.yaml``, env overrides spelled ``CLIVER_RAG__<FIELD>``, field
defaults last — and a composed application's ``create_app`` binds this
most-derived instance to the process runtime, which every package's
``settings`` proxy then serves (ADR-0016).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cliver_playbook.app.basic.runtime import lazy_settings
from cliver_playbook.app.user.settings import Settings as UserSettings


class RagSettings(BaseModel):
    """RAG block (see ``app.yaml``'s ``rag:`` section for the narrative)."""

    # The five RAG stages, named. Every name resolves through a registry
    # in its own module; the default names below are all offline-capable
    # (no API key, no external service).
    chunker: str = "recursive"  # recursive | markdown | code | pdf
    embedder: str = "bge-m3"  # bge-m3 | stub | openai
    retriever: str = "pgvector-hybrid"  # pgvector-hybrid | bm25-only
    reranker: str = "bge-reranker-v2-m3"  # bge-reranker-v2-m3 | noop
    llm: str = "stub"  # stub | openai

    # Recursive chunker defaults. Markdown/code/pdf chunkers each have
    # their own internal size logic but consult these for "the chunk is
    # too long" overflow.
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Search / chat. ``top_k`` is the size of the retriever's result
    # list before the reranker; the reranker then drops it to
    # ``rerank_top_k`` before the LLM sees the context.
    top_k: int = 20
    rerank_top_k: int = 5
    # Chat drops hits whose reranker relevance score is below this
    # floor; if nothing survives, the generator is skipped and the
    # response is an explicit "no relevant context" refusal, so neither
    # the stub nor a real model can produce a hallucinated answer. The
    # floor applies only to rerankers that produce normalized relevance
    # scores (a real cross-encoder) — retriever scores (RRF sums,
    # cosine, ts_rank_cd) are on other scales. Set to 0.0 to disable.
    score_floor: float = 0.2

    # pgvector HNSW tuning. ``lists`` is the number of coarse
    # clusters; the actual query-time ``ef_search`` is the SQL session
    # setting on the retriever, not a Settings field.
    pgvector_ef_search: int = 40


class Settings(UserSettings):
    """Identity settings plus the ``rag`` block."""

    rag: RagSettings = Field(default_factory=RagSettings)


# Process-aware lazy proxy (see basic.runtime.lazy_settings): resolves
# to the runtime-bound instance — this class, or any composed
# application's Settings — or to a lazily built Settings() of this
# class when unconfigured.
settings = lazy_settings(Settings)


def get_settings() -> Settings:
    """Return the process-wide Settings instance (see ``settings`` above)."""
    return settings.resolve()
