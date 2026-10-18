"""Search endpoint: run the retrieval stage and return ranked chunks.

Search is exposed separately from chat so the web UI can demonstrate
each stage on its own: a user can inspect exactly which chunks the
retriever returns, with scores and metadata, before a reranker or an
LLM touches them. The retriever is resolved by name from the registry,
defaulting to ``settings.rag.retriever``; the request may override it
(and ``top_k`` / ``mode``) for one call, which is how the UI makes the
stage selectable without a restart.

The audit row records the retriever, mode, and hit count — never the
raw query text. Queries can carry user-specific content, and an audit
table is long-lived; the target is an opaque fingerprint instead.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import write_rag_audit
from cliver_playbook.app.rag.retrieval import Query, get_retriever
from cliver_playbook.app.rag.schemas.search import HitRead, SearchRequest, SearchResponse
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/rag/search", tags=["rag-search"])

_READ = Security(require_perm("rag:search:read"))


def _query_fingerprint(query_text: str) -> str:
    """Stable short hash of a query, for audit rows without the text."""
    return hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:12]


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> SearchResponse:
    """Retrieve the chunks most relevant to ``request.query``.

    Returns 200 with an empty ``hits`` list when the index is empty or
    nothing matches: "no results" is a normal answer, not an error.
    """
    retriever_name = request.retriever or settings.rag.retriever
    try:
        retriever = get_retriever(retriever_name)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"unknown retriever: {retriever_name!r}"
        ) from None

    top_k = request.top_k if request.top_k is not None else settings.rag.top_k
    query = Query(text=request.query, top_k=top_k, mode=request.mode)
    hits = await retriever.retrieve(query, db=db)

    await write_rag_audit(
        event="search.run",
        target=_query_fingerprint(request.query),
        ok=True,
        args={"retriever": retriever_name, "mode": request.mode},
        extra={"hit_count": len(hits), "top_k": top_k},
    )
    return SearchResponse(
        retriever=retriever_name,
        mode=request.mode,
        hits=[HitRead(**hit.model_dump()) for hit in hits],
    )
