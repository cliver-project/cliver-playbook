"""LLM protocol and its implementations.

The generator is the fifth RAG stage. ``stub`` is the offline default;
``cliver-core`` performs real model calls through the cliver-core agent
core. New implementations register themselves here without touching the
chat endpoint.
"""

from __future__ import annotations

from cliver_playbook.app.rag.llm.base import LLM
from cliver_playbook.app.rag.llm.registry import get_llm, registry

__all__ = ["LLM", "get_llm", "registry"]
