"""Embeddings backed by cliver-core.

cliver-core owns the transport: ``ModelBinding.embed`` describes the model,
endpoint, credentials and default request options, and ``cliver_core.embed``
performs the call. This adapter is only the RAG seam — it validates that the
provider returned one vector per text at the configured size and reports the
same ``id``/``dim`` metadata every embedder stage exposes.

The RAG embedder protocol is synchronous because callers already run it in a
worker thread (``asyncio.to_thread``). This adapter therefore executes the
async cliver-core call with ``asyncio.run`` on that thread's private loop, and
builds/closes one binding per call: a provider's HTTP client is bound to the
loop that created it, so a process-wide client cannot be reused across the
short-lived loops of successive requests.

``mode`` is accepted for protocol compatibility and ignored — remote
embeddings endpoints have no query/document distinction, so the stage reports
``supports_query_document_modes = False``.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Literal

from cliver_core import ModelBinding
from cliver_core import embed as cliver_embed

from cliver_playbook.app.rag.settings import CliverEmbedSettings, settings

# Advisory upper bound, matching the other remote-capable stages. Nothing in
# the pipeline enforces it; it feeds the per-chunk token estimate only.
_MAX_INPUT_TOKENS = 8192

# ``rag_chunk_embeddings.embedder_version`` is String(64). The id must change
# with the model AND the declared size: retrieval filters stored vectors by
# this value, so a stale id would compare vectors from different spaces.
_ID_LIMIT = 64


def _embedder_id(model: str, dim: int) -> str:
    raw = f"cliver-core@{model}@{dim}"
    if len(raw) <= _ID_LIMIT:
        return raw
    # Long model names still need a stable id that fits the column. The
    # digest keeps distinct configurations distinct where truncation alone
    # could collide.
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"cliver-core#{digest}@{dim}"


class CliverCoreEmbedder:
    """The ``cliver-core`` embeddings stage."""

    max_input_tokens = _MAX_INPUT_TOKENS
    supports_query_document_modes = False

    def __init__(self, config: CliverEmbedSettings | None = None) -> None:
        """Take an explicit config (tests); otherwise follow the live settings."""
        self._explicit_config = config

    @property
    def config(self) -> CliverEmbedSettings:
        """The binding in force now — read live so runtime edits apply."""
        if self._explicit_config is not None:
            return self._explicit_config
        return settings.rag.cliver_embed

    @property
    def id(self) -> str:
        """Corpus identity: changes when the model or vector size changes."""
        config = self.config
        if not config.model:
            return "cliver-core@unconfigured"
        return _embedder_id(config.model, config.dim)

    @property
    def dim(self) -> int:
        return self.config.dim

    def binding(self) -> ModelBinding:
        """Build the embeddings binding from configuration (no network I/O)."""
        config = self.config
        if not config.model:
            raise RuntimeError(
                "the cliver-core embedder is not configured: set "
                "rag.cliver_embed.model (CLIVER_RAG__CLIVER_EMBED__MODEL)"
            )
        if not config.base_url and not config.provider_name:
            raise RuntimeError(
                "the cliver-core embedder needs rag.cliver_embed.base_url or "
                "rag.cliver_embed.provider_name "
                "(CLIVER_RAG__CLIVER_EMBED__BASE_URL / __PROVIDER_NAME)"
            )
        # Embeddings are a one-shot OpenAI-shaped POST. cliver-core defines no
        # Anthropic-protocol embeddings endpoint, so the protocol is fixed and
        # not a setting.
        return ModelBinding.embed(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            protocol="openai",
            provider_name=config.provider_name or None,
            path=config.path or None,
            **config.params,
        )

    def embed(
        self,
        texts: list[str],
        *,
        mode: Literal["query", "document", "unspecified"] = "document",
    ) -> list[list[float]]:
        """Return one vector per text.

        ``mode`` is accepted and ignored (see the module docstring).
        """
        return asyncio.run(self._embed(texts))

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        binding = self.binding()
        try:
            result = await cliver_embed(texts=texts, binding=binding)
        finally:
            await binding.aclose()

        vectors = result.vectors
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"the cliver-core embedder returned {len(vectors)} vectors for {len(texts)} texts"
            )
        expected = self.dim
        for index, vector in enumerate(vectors):
            if len(vector) != expected:
                raise RuntimeError(
                    "the cliver-core embedder returned a "
                    f"{len(vector)}-d vector at index {index}, but "
                    f"rag.cliver_embed.dim is {expected}; set dim to the model's "
                    "output size (CLIVER_RAG__CLIVER_EMBED__DIM)"
                )
        return vectors

    def estimate_tokens(self, text: str) -> int:
        """Approximate token count for display and chunk metadata.

        Remote embedding APIs expose no local tokenizer; four characters per
        token is the usual English rule of thumb and a conservative estimate
        for CJK text.
        """
        return 0 if not text else max(1, (len(text) + 3) // 4)
