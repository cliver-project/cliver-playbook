"""Offline generator: echoes the grounded prompt.

The stub exists so the full chat pipeline is demonstrable without an
API key or a local model: the client receives exactly the context the
retriever and reranker selected, framed by the system prompt, which is
enough to verify that every stage did its job. It is honest about being
a stub — the banner says so — and never fabricates an answer.

The plan sketched a stub that formatted the hit list directly, but the
LLM seam receives a prompt, not hits. Echoing the prompt keeps the seam
clean: the prompt already contains the numbered context.
"""

from __future__ import annotations

_BANNER = (
    "[stub] No language model is configured, so the retrieved context is "
    "shown verbatim instead of an answer.\n\n"
)


class StubLLM:
    """Deterministic, offline generator used as the default."""

    name = "stub"
    model_id = "stub@1.0"

    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        # `system` and `max_tokens` are accepted for interface parity;
        # an echo has nothing to configure.
        return _BANNER + prompt
