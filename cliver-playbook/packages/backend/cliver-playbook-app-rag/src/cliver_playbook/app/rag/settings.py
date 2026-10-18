"""Application settings for the ``rag`` package.

Extends ``user.Settings`` (identity, OIDC registry, OAuth 2.1 provider)
with the single ``rag`` block: which chunker / embedder / retriever /
reranker / LLM the composed app uses by name, the chunk-size defaults,
the search top-k, and the score floor. A name in this block is not
validated at startup — the registries live in modules that import this
one — so an unknown name surfaces as a 422 from the endpoint that uses
the stage, and ``GET /api/v1/rag/stages`` always reports the live set. The full layered resolution
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
    # in its own module. The field defaults are the offline-safe set: the
    # stub embedder and noop reranker download nothing, and the stub LLM
    # needs no API key, so a package used without an app.yaml still works
    # on a fresh machine. Production stages (``bge-m3``,
    # ``bge-reranker-v2-m3``) are an explicit override.
    chunker: str = "recursive"  # recursive | markdown | code | pdf
    embedder: str = "stub"  # stub | bge-m3
    retriever: str = "pgvector-hybrid"  # pgvector-hybrid | bm25-only
    reranker: str = "noop"  # noop | bge-reranker-v2-m3
    llm: str = "stub"  # stub

    # Recursive chunker defaults. Markdown/code/pdf chunkers each have
    # their own internal size logic but consult these for "the chunk is
    # too long" overflow.
    chunk_size: int = Field(default=512, ge=1)
    chunk_overlap: int = Field(default=64, ge=0)

    # Search / chat. ``top_k`` is the size of the retriever's result
    # list before the reranker; the reranker then drops it to
    # ``rerank_top_k`` before the LLM sees the context.
    top_k: int = Field(default=20, ge=1)
    rerank_top_k: int = Field(default=5, ge=1)
    # Chat drops hits whose reranker relevance score is below this
    # floor; if nothing survives, the generator is skipped and the
    # response is an explicit "no relevant context" refusal, so neither
    # the stub nor a real model can produce a hallucinated answer. The
    # floor applies only to rerankers that produce normalized relevance
    # scores (a real cross-encoder) — retriever scores (RRF sums,
    # cosine, ts_rank_cd) are on other scales. Set to 0.0 to disable.
    score_floor: float = Field(default=0.2, ge=0.0, le=1.0)

    # pgvector HNSW search breadth: the number of candidates the index
    # explores per query. The retriever raises it to at least the query
    # LIMIT, because HNSW returns at most ef_search rows.
    pgvector_ef_search: int = Field(default=40, ge=1)

    # Upload cap. The endpoint reads at most one byte past this bound
    # and rejects anything larger before parsing, so a hostile or
    # accidental huge file cannot exhaust memory or the chunker. The
    # default (20 MiB) comfortably covers text documents and keeps
    # PDFs in a sane range for an in-process parser.
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)


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
