"""LLM protocol + the offline stub generator.

The generator is the fifth RAG stage. ``get_llm(name)`` currently
returns ``stub``; hosted or local generators register themselves here
without touching the chat endpoint.
"""

from __future__ import annotations

from cliver_playbook.app.rag.llm.base import LLM
from cliver_playbook.app.rag.llm.registry import get_llm, registry

__all__ = ["LLM", "get_llm", "registry"]
