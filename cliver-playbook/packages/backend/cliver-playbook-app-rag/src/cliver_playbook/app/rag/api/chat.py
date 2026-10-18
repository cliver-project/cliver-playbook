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
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import fingerprint, write_rag_audit
from cliver_playbook.app.rag.llm import get_llm
from cliver_playbook.app.rag.reranking import get_reranker
from cliver_playbook.app.rag.retrieval import Query, get_retriever
from cliver_playbook.app.rag.retrieval.base import Hit
from cliver_playbook.app.rag.schemas.chat import ChatRequest, ChatResponse, Citation
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

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
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> ChatResponse:
    """Answer ``request.question`` from the knowledge base, with citations."""
    retriever_name = request.retriever or settings.rag.retriever
    reranker_name = request.reranker or settings.rag.reranker
    llm_name = request.llm or settings.rag.llm

    # Resolve every stage before doing any work: an unknown name is a
    # client error and should not cost a retrieval round trip.
    try:
        retriever = get_retriever(retriever_name)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"unknown retriever: {retriever_name!r}"
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

    top_k = request.top_k if request.top_k is not None else settings.rag.top_k
    rerank_top_k = (
        request.rerank_top_k if request.rerank_top_k is not None else settings.rag.rerank_top_k
    )

    hits = await retriever.retrieve(
        Query(text=request.question, top_k=top_k, mode=request.mode),
        db=db,
    )
    if hits:
        # Cross-encoder inference is CPU/model work; keep it off the loop.
        hits = await asyncio.to_thread(reranker.rerank, request.question, hits, top_k=rerank_top_k)
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
            prompt=_build_prompt(request.question, hits),
            max_tokens=_MAX_TOKENS,
        )

    await write_rag_audit(
        event="chat.run",
        target=fingerprint(request.question),
        ok=not no_hits,
        args={"retriever": retriever_name, "reranker": reranker_name, "llm": llm_name},
        extra={
            "hit_count": len(hits),
            "model_id": llm.model_id,
            "no_hits": no_hits,
            **({"error": "no_hits"} if no_hits else {}),
        },
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
        reranker=reranker_name,
        llm=llm_name,
    )
