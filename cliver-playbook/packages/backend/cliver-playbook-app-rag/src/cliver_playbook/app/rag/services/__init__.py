"""Pure data-access services for the RAG package.

Routers own the HTTP contract (status codes, response models); services
own the queries. No business rules live here, which keeps the same
functions reusable from the chat/search routes and from tests.
"""

from __future__ import annotations

from cliver_playbook.app.rag.services.documents import (
    get_document,
    list_chunks,
    list_documents,
)

__all__ = ["get_document", "list_chunks", "list_documents"]
