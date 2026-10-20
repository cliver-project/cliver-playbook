"""Stage discovery: the catalog the web UI builds its selectors from.

Every stage has a registry that knows its implementations' names; the
UI must not duplicate those lists. This endpoint serializes all five
registries plus the configured defaults, so adding a new chunker (or
embedder, retriever, reranker, LLM) makes it selectable with no
frontend change.

Instantiating an implementation to read metadata is cheap across the
board: model-backed stages load lazily on first use, not construction.

Permissions: the catalog is ordinary read metadata (the upload page
needs it before the user has chosen a document), so it is gated by
``rag:documents:read`` rather than the admin code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.chunking import registry as chunker_registry
from cliver_playbook.app.rag.chunking.options import describe_options
from cliver_playbook.app.rag.embedding import registry as embedder_registry
from cliver_playbook.app.rag.llm import registry as llm_registry
from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag.reranking import registry as reranker_registry
from cliver_playbook.app.rag.retrieval import registry as retriever_registry
from cliver_playbook.app.rag.schemas.stages import (
    CorpusStats,
    StageCatalog,
    StageDefaults,
    StageOption,
    StageOptionField,
)
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_any_perm

router = APIRouter(prefix="/api/v1/rag/stages", tags=["rag-stages"])

# The catalog is read metadata shared by every RAG page, so any of the
# read permissions is enough. A single code would make a chat-only role
# fetch stages it is not allowed to see.
_READ = Security(require_any_perm("rag:documents:read", "rag:search:read", "rag:chat:read"))


def _options(names: set[str], get) -> list[StageOption]:
    """Sorted options with whatever metadata the implementation exposes."""
    options: list[StageOption] = []
    for name in sorted(names):
        impl = get(name)
        modes = getattr(impl, "modes", None)
        options_model = getattr(impl, "options_model", None)
        options.append(
            StageOption(
                name=name,
                model_id=getattr(impl, "model_id", None) or getattr(impl, "id", None),
                version=getattr(impl, "version", None),
                dim=getattr(impl, "dim", None),
                modes=sorted(modes) if modes else None,
                config_schema=(
                    [StageOptionField(**field) for field in describe_options(options_model)]
                    if options_model is not None
                    else None
                ),
            )
        )
    return options


async def _corpus_embedders(db: AsyncSession) -> list[str]:
    """Embedder ids that actually produced indexed rows."""
    rows = await db.execute(
        select(Document.embedder_id)
        .where(Document.status == "indexed")
        .distinct()
        .order_by(Document.embedder_id)
    )
    return [row[0] for row in rows]


@router.get("", response_model=StageCatalog)
async def list_stages(
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> StageCatalog:
    """Every registered stage implementation, the defaults, and corpus stats."""
    return StageCatalog(
        chunkers=_options(chunker_registry.names(), chunker_registry.get),
        embedders=_options(embedder_registry.names(), embedder_registry.get),
        retrievers=_options(retriever_registry.names(), retriever_registry.get),
        rerankers=_options(reranker_registry.names(), reranker_registry.get),
        llms=_options(llm_registry.names(), llm_registry.get),
        defaults=StageDefaults(
            chunker=settings.rag.chunker,
            embedder=settings.rag.embedder,
            retriever=settings.rag.retriever,
            reranker=settings.rag.reranker,
            llm=settings.rag.llm,
        ),
        corpus=CorpusStats(embedders=await _corpus_embedders(db)),
    )
