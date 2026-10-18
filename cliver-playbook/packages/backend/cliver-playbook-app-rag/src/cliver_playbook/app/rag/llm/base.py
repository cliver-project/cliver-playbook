"""LLM protocol.

The generator is the fifth RAG stage. It is synchronous (inference,
possibly remote over the network) and knows nothing about retrieval:
the caller assembles the grounded prompt and receives plain text. That
keeps the seam swappable — a stub, a local model, and a hosted API all
implement the same two methods.

``generate`` takes keyword arguments so an implementation cannot
silently depend on argument order. ``model_id`` is recorded in the
audit row and returned to the client, making the answer's provenance
explicit.
"""

from __future__ import annotations

from typing import Protocol


class LLM(Protocol):
    """The generator seam.

    Implementations: ``StubLLM`` (echoes the grounded prompt, no model)
    and, in a future patch, hosted or local generators. New
    implementations register themselves at import via
    ``llm.registry.register(name, factory)``.
    """

    name: str
    model_id: str

    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str: ...
