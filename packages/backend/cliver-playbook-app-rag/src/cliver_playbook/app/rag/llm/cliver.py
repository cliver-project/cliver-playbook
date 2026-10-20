"""Generator backed by cliver-core.

cliver-core owns the provider transport: one ``ModelBinding`` describes the
model, endpoint, credentials and default request options, and
``AgentCore.chat`` performs the call — including tool calling and the
agentic loop when tools are supplied. The RAG generator supplies no tools:
the grounded prompt is the whole input and the final assistant message is
the answer, so the loop terminates after one model turn.

The RAG LLM seam is synchronous because the chat endpoint already runs
generation in a worker thread. This adapter therefore executes the async
cliver-core call on a private event loop. An ``AgentCore`` (and the
provider it builds) is created per call and closed in ``finally``: a
provider's HTTP client stays bound to the loop that created it, so a
process-wide instance could not be reused across short-lived loops. The
cost is client construction per request, not model loading — the remote
model is stateless.

Configuration lives in ``rag.cliver_llm`` (see ``CliverLLMSettings``).
Nothing is validated at import or construction time: the stage catalog
instantiates every registered implementation to read metadata, and an
unconfigured deployment must still be able to browse stages and use the
offline stub.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cliver_core import AgentCore, ModelBinding, ModelBindings

from cliver_playbook.app.rag.settings import CliverLLMSettings, settings


def _text_of(content: str | list[dict[str, Any]] | None) -> str:
    """Flatten cliver-core message content into plain text.

    A chat response is normally a string. Multimodal content arrives as a
    list of blocks; text blocks are concatenated and non-text blocks are
    ignored because the RAG answer is text-only.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in content if isinstance(block.get("text"), str))


class CliverCoreLLM:
    """The ``cliver-core`` RAG generator stage."""

    name = "cliver-core"

    def __init__(self, config: CliverLLMSettings | None = None) -> None:
        # An explicit config pins the instance (tests, alternate bindings).
        # Otherwise the binding is resolved per use, not captured here: the
        # registry caches one instance per stage for the process lifetime and
        # the settings section mutates the nested object in place, so a live
        # lookup keeps both the request and its provenance label current.
        self._explicit_config = config

    @property
    def config(self) -> CliverLLMSettings:
        """The binding in force now — explicit, or the process settings."""
        if self._explicit_config is not None:
            return self._explicit_config
        return settings.rag.cliver_llm

    @property
    def model_id(self) -> str:
        """The configured model, read live so it survives runtime edits."""
        model = self.config.model
        return f"cliver-core@{model}" if model else "cliver-core@unconfigured"

    def binding(self) -> ModelBinding:
        """Build the chat binding from configuration (no network I/O).

        A model and a way to reach it are the only hard requirements: the
        endpoint comes from ``base_url`` or from the brand's default when
        ``provider_name`` is set. Failing here gives the operator an
        actionable message instead of a provider-level transport error.
        """
        config = self.config
        if not config.model:
            raise RuntimeError(
                "the cliver-core LLM stage is not configured: set "
                "rag.cliver_llm.model (CLIVER_RAG__CLIVER_LLM__MODEL)"
            )
        if not config.base_url and not config.provider_name:
            raise RuntimeError(
                "the cliver-core LLM stage needs rag.cliver_llm.base_url or "
                "rag.cliver_llm.provider_name "
                "(CLIVER_RAG__CLIVER_LLM__BASE_URL / __PROVIDER_NAME)"
            )
        return ModelBinding.llm(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            protocol=config.protocol,
            provider_name=config.provider_name or None,
            **config.params,
        )

    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        """Run one grounded completion and return its text.

        ``asyncio.run`` is safe here because the caller invokes this from a
        worker thread (``asyncio.to_thread``), where no event loop runs.
        """
        return asyncio.run(self._generate(system=system, prompt=prompt, max_tokens=max_tokens))

    async def _generate(self, *, system: str, prompt: str, max_tokens: int) -> str:
        agent = AgentCore(ModelBindings(llm=self.binding()))
        try:
            response = await agent.chat(
                prompt,
                system_prompt=system,
                options={"max_tokens": max_tokens},
            )
        finally:
            await agent.aclose()
        return _text_of(response.message.content)
