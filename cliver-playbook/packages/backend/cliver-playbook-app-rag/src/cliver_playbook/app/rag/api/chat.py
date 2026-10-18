"""Chat endpoint: retrieve -> rerank -> generate, grounded in chunk ids.

The endpoint is the whole RAG pipeline in one request, and every stage
is selectable per call (``retriever`` / ``reranker`` / ``llm`` plus the
two top-k bounds), which is what lets the web UI demonstrate the stack
without restarting the server.

Grounding rules:

- The generator is skipped entirely when retrieval (or the relevance
  floor) leaves no context. The response is then an explicit "could not
  find" refusal with no citations, never an ungrounded answer.
- The prompt instructs the generator to answer only from the supplied
  context and to cite chunk ids in square brackets. Citations returned
  to the client are the exact chunk rows the context was built from, so
  the UI can link every answer back to its source.
- ``score_floor`` applies only when the reranker produces normalized
  relevance scores (a real cross-encoder). A reranker that passes the
  retriever's scores through (noop) has no relevance scale, so a floor
  in relevance units would be meaningless and is skipped.

Like search, the endpoint validates the retriever's declared modes,
reports the mode that actually ran, and audits both outcomes with the
caller's identity. A request that completes without context is a
successful refusal (``ok=True`` with ``no_hits`` in the detail): the
pipeline did its job, it just found nothing to ground an answer in.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import fingerprint, write_rag_audit
from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.llm import get_llm
from cliver_playbook.app.rag.reranking import get_reranker
from cliver_playbook.app.rag.retrieval import Query, get_retriever
from cliver_playbook.app.rag.retrieval.base import Hit
from cliver_playbook.app.rag.schemas.chat import ChatRequest, ChatResponse, Citation
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

logger = logging.getLogger("cliver_playbook.app.rag.api.chat")

router = APIRouter(prefix="/api/v1/rag/chat", tags=["rag-chat"])

_READ = Security(require_perm("rag:chat:read"))

_NO_CONTEXT_ANSWER = (
    "I could not find anything relevant to that question in the knowledge base. "
    "Try rephrasing it, or upload a document that covers the topic."
)
_MAX_TOKENS = 1024
_PREVIEW_CHARS = 200

_SYSTEM_PROMPT = (
    "You are a retrieval-augmented assistant. Answer the question using ONLY the "
    "provided context. Cite each claim with the chunk id shown in square brackets, "
    "for example [0123abcd]. If the context does not contain the answer, say so "
    "plainly instead of guessing."
)


def _build_prompt(question: str, hits: list[Hit]) -> str:
    """Assemble the grounded prompt. Chunk ids are visible so the
    generator can cite them and the user can verify the citation."""
    context = "\n\n".join(f"[{hit.chunk_id}] {hit.text}" for hit in hits)
    return f"Context:\n{context}\n\nQuestion: {question}"


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _READ,
) -> ChatResponse:
    """Answer ``payload.question`` from the knowledge base, with citations."""
    retriever_name = payload.retriever or settings.rag.retriever
    reranker_name = payload.reranker or settings.rag.reranker
    llm_name = payload.llm or settings.rag.llm

    # Resolve every stage before doing any work: an unknown name is a
    # client error and should not cost a retrieval round trip.
    try:
        retriever = get_retriever(retriever_name)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"unknown retriever: {retriever_name!r}"
        ) from None
    if payload.mode not in retriever.modes:
        raise HTTPException(
            status_code=422,
            detail=(
                f"retriever {retriever_name!r} does not support mode "
                f"{payload.mode!r}; supported: {', '.join(sorted(retriever.modes))}"
            ),
        )
    if payload.embedder is not None:
        try:
            get_embedder(payload.embedder)
        except KeyError:
            raise HTTPException(
                status_code=422, detail=f"unknown embedder: {payload.embedder!r}"
            ) from None
    try:
        reranker = get_reranker(reranker_name)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"unknown reranker: {reranker_name!r}"
        ) from None
    try:
        llm = get_llm(llm_name)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"unknown llm: {llm_name!r}") from None

    top_k = payload.top_k if payload.top_k is not None else settings.rag.top_k
    rerank_top_k = (
        payload.rerank_top_k if payload.rerank_top_k is not None else settings.rag.rerank_top_k
    )
    effective_mode = retriever.effective_mode(payload.mode)
    audit_args = {
        "retriever": retriever_name,
        "mode": payload.mode,
        "effective_mode": effective_mode,
        "embedder": payload.embedder or settings.rag.embedder,
        "reranker": reranker_name,
        "llm": llm_name,
    }

    try:
        hits = await retriever.retrieve(
            Query(
                text=payload.question,
                top_k=top_k,
                mode=payload.mode,
                embedder=payload.embedder,
            ),
            db=db,
        )
        if hits:
            # Cross-encoder inference is CPU/model work; keep it off the loop.
            hits = await asyncio.to_thread(
                reranker.rerank, payload.question, hits, top_k=rerank_top_k
            )
            floor = settings.rag.score_floor
            if reranker.produces_relevance_scores and floor > 0:
                hits = [hit for hit in hits if hit.score >= floor]

        no_hits = not hits
        if no_hits:
            answer = _NO_CONTEXT_ANSWER
        else:
            answer = await asyncio.to_thread(
                llm.generate,
                system=_SYSTEM_PROMPT,
                prompt=_build_prompt(payload.question, hits),
                max_tokens=_MAX_TOKENS,
            )
    # Retrieval, reranking and generation all fail in third-party ways;
    # the client gets one stable server-error contract and the audit row
    # carries the stage-agnostic failure tag.
    except Exception:
        logger.exception("chat pipeline failed (retriever=%s)", retriever_name)
        await write_rag_audit(
            event="chat.run",
            target=fingerprint(payload.question),
            ok=False,
            args=audit_args,
            extra={"error": "pipeline_failed"},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(status_code=500, detail="chat failed") from None

    await write_rag_audit(
        event="chat.run",
        target=fingerprint(payload.question),
        # A grounded refusal is a completed request, not a failure: the
        # pipeline ran and correctly found nothing to cite.
        ok=True,
        args=audit_args,
        extra={
            "hit_count": len(hits),
            "model_id": llm.model_id,
            "no_hits": no_hits,
        },
        viewer=viewer,
        request=request,
    )

    return ChatResponse(
        answer=answer,
        citations=[
            Citation(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                ordinal=hit.ordinal,
                score=hit.score,
                text_preview=hit.text[:_PREVIEW_CHARS],
            )
            for hit in hits
        ],
        model_id=llm.model_id,
        hits_used=len(hits),
        no_hits=no_hits,
        retriever=retriever_name,
        requested_mode=payload.mode,
        mode=effective_mode,
        reranker=reranker_name,
        llm=llm_name,
    )
