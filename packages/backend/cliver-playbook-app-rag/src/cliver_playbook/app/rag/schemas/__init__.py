"""Pydantic wire models for the RAG HTTP surface."""

from __future__ import annotations

from cliver_playbook.app.rag.schemas.chat import ChatRequest, ChatResponse, Citation
from cliver_playbook.app.rag.schemas.documents import (
    ChunkList,
    ChunkRead,
    DocumentList,
    DocumentRead,
)
from cliver_playbook.app.rag.schemas.search import (
    HitRead,
    SearchRequest,
    SearchResponse,
)
from cliver_playbook.app.rag.schemas.stages import StageCatalog, StageDefaults, StageOption

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ChunkList",
    "ChunkRead",
    "Citation",
    "DocumentList",
    "DocumentRead",
    "HitRead",
    "SearchRequest",
    "SearchResponse",
    "StageCatalog",
    "StageDefaults",
    "StageOption",
]
