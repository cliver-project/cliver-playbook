"""Reranking backed by cliver-core.

cliver-core owns the transport: ``ModelBinding.rerank`` describes the model,
endpoint, credentials and default request options, and ``cliver_core.rerank``
performs the call. This adapter maps the returned ``(index, relevance_score)``
items back onto the retriever's hits and reorders them.

The RAG reranker protocol is synchronous because the chat endpoint runs it in
a worker thread (``asyncio.to_thread``). This adapter executes the async
cliver-core call with ``asyncio.run`` on that thread's private loop and builds
and closes one binding per call — a provider's HTTP client is bound to the
loop that created it, so it cannot be shared across short-lived loops.

The provider's rerank endpoint returns a normalized relevance score, which is
the scale ``rag.score_floor`` is defined on, so the stage reports
``produces_relevance_scores = True``.
"""

from __future__ import annotations

import asyncio

from cliver_core import ModelBinding
from cliver_core import rerank as cliver_rerank

from cliver_playbook.app.rag.retrieval.base import Hit
from cliver_playbook.app.rag.settings import CliverRerankSettings, settings


class CliverCoreReranker:
    """The ``cliver-core`` rerank stage."""

    name = "cliver-core"
    produces_relevance_scores = True

    def __init__(self, config: CliverRerankSettings | None = None) -> None:
        """Take an explicit config (tests); otherwise follow the live settings."""
        self._explicit_config = config

    @property
    def config(self) -> CliverRerankSettings:
        """The binding in force now — read live so runtime edits apply."""
        if self._explicit_config is not None:
            return self._explicit_config
        return settings.rag.cliver_rerank

    @property
    def model_id(self) -> str:
        """The configured model, read live so it survives runtime edits."""
        model = self.config.model
        return f"cliver-core@{model}" if model else "cliver-core@unconfigured"

    def binding(self) -> ModelBinding:
        """Build the rerank binding from configuration (no network I/O)."""
        config = self.config
        if not config.model:
            raise RuntimeError(
                "the cliver-core reranker is not configured: set "
                "rag.cliver_rerank.model (CLIVER_RAG__CLIVER_RERANK__MODEL)"
            )
        if not config.base_url and not config.provider_name:
            raise RuntimeError(
                "the cliver-core reranker needs rag.cliver_rerank.base_url or "
                "rag.cliver_rerank.provider_name "
                "(CLIVER_RAG__CLIVER_RERANK__BASE_URL / __PROVIDER_NAME)"
            )
        # Rerank is a one-shot Cohere/Jina/GLM-shaped POST. cliver-core defines
        # no Anthropic-protocol rerank endpoint, so the protocol is fixed and
        # not a setting.
        return ModelBinding.rerank(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            protocol="openai",
            provider_name=config.provider_name or None,
            path=config.path or None,
            **config.params,
        )

    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]:
        if not hits:
            return []
        return asyncio.run(self._rerank(query, hits, top_k))

    async def _rerank(self, query: str, hits: list[Hit], top_k: int | None) -> list[Hit]:
        binding = self.binding()
        try:
            items = await cliver_rerank(
                query=query,
                documents=[hit.text for hit in hits],
                binding=binding,
                top_k=top_k,
            )
        finally:
            await binding.aclose()

        scored: list[Hit] = []
        for item in items:
            if not 0 <= item.index < len(hits):
                continue
            scored.append(hits[item.index].model_copy(update={"score": item.relevance_score}))
        # Providers return best-first; sorting makes the order independent of
        # that promise, and the slice mirrors the noop/BGE contract.
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:top_k] if top_k is not None else scored
