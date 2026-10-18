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

from fastapi import APIRouter, Security

from cliver_playbook.app.rag.chunking import registry as chunker_registry
from cliver_playbook.app.rag.embedding import registry as embedder_registry
from cliver_playbook.app.rag.llm import registry as llm_registry
from cliver_playbook.app.rag.reranking import registry as reranker_registry
from cliver_playbook.app.rag.retrieval import registry as retriever_registry
from cliver_playbook.app.rag.schemas.stages import StageCatalog, StageDefaults, StageOption
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag/stages", tags=["rag-stages"])

_READ = Security(require_perm("rag:documents:read"))


def _options(names: set[str], get) -> list[StageOption]:
    """Sorted options with whatever metadata the implementation exposes."""
    options: list[StageOption] = []
    for name in sorted(names):
        impl = get(name)
        options.append(
            StageOption(
                name=name,
                model_id=getattr(impl, "model_id", None) or getattr(impl, "id", None),
                version=getattr(impl, "version", None),
                dim=getattr(impl, "dim", None),
            )
        )
    return options


@router.get("", response_model=StageCatalog)
async def list_stages(_viewer: Viewer = _READ) -> StageCatalog:
    """Every registered stage implementation plus the configured defaults."""
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
    )
