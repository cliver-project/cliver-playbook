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
table is long-lived; the target is an opaque fingerprint instead. Rows
carry the caller's identity and request metadata whenever the handler
has them, so a search can always be attributed after the fact; a failed
retrieval is audited as a failure rather than leaving no trace.

Mode handling is explicit: each retriever declares the modes it can
honour, an unsupported combination is a 422, and the response reports
the mode that actually ran (a lexical-only retriever reports ``sparse``
for a ``hybrid`` request) rather than echoing the request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import fingerprint, write_rag_audit
from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.retrieval import Query, get_retriever
from cliver_playbook.app.rag.schemas.search import HitRead, SearchRequest, SearchResponse
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

logger = logging.getLogger("cliver_playbook.app.rag.api.search")

router = APIRouter(prefix="/api/v1/rag/search", tags=["rag-search"])

_READ = Security(require_perm("rag:search:read"))


@router.post("", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _READ,
) -> SearchResponse:
    """Retrieve the chunks most relevant to ``payload.query``.

    Returns 200 with an empty ``hits`` list when the index is empty or
    nothing matches: "no results" is a normal answer, not an error.
    """
    retriever_name = payload.retriever or settings.rag.retriever
    try:
        retriever = get_retriever(retriever_name)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"unknown retriever: {retriever_name!r}"
        ) from None
    # A retriever that cannot run the requested leg combination must be
    # rejected, not silently downgraded: a user comparing dense vs
    # hybrid results would otherwise be shown lexical hits labelled
    # "dense". `modes` is the implementation's declared capability set.
    if payload.mode not in retriever.modes:
        raise HTTPException(
            status_code=422,
            detail=(
                f"retriever {retriever_name!r} does not support mode "
                f"{payload.mode!r}; supported: {', '.join(sorted(retriever.modes))}"
            ),
        )
    # Validate the query embedder up front: an unknown name would
    # otherwise surface as a 500 from inside the dense leg, after a
    # database round trip.
    if payload.embedder is not None:
        try:
            get_embedder(payload.embedder)
        except KeyError:
            raise HTTPException(
                status_code=422, detail=f"unknown embedder: {payload.embedder!r}"
            ) from None

    top_k = payload.top_k if payload.top_k is not None else settings.rag.top_k
    query = Query(
        text=payload.query,
        top_k=top_k,
        mode=payload.mode,
        embedder=payload.embedder,
    )
    audit_args = {
        "retriever": retriever_name,
        "mode": payload.mode,
        "embedder": payload.embedder or settings.rag.embedder,
    }
    try:
        hits = await retriever.retrieve(query, db=db)
    # A storage or model failure is a server error with a stable
    # contract; the audit row keeps the diagnosis out of the response.
    except Exception:
        logger.exception("retrieval failed for retriever=%s", retriever_name)
        await write_rag_audit(
            event="search.run",
            target=fingerprint(payload.query),
            ok=False,
            args=audit_args,
            extra={"error": "retrieval_failed"},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(status_code=500, detail="retrieval failed") from None

    effective_mode = retriever.effective_mode(payload.mode)
    await write_rag_audit(
        event="search.run",
        target=fingerprint(payload.query),
        ok=True,
        args={**audit_args, "effective_mode": effective_mode},
        extra={"hit_count": len(hits), "top_k": top_k},
        viewer=viewer,
        request=request,
    )
    return SearchResponse(
        retriever=retriever_name,
        requested_mode=payload.mode,
        mode=effective_mode,
        hits=[HitRead(**hit.model_dump()) for hit in hits],
    )
