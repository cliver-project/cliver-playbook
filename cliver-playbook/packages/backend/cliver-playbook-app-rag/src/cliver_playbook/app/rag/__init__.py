"""rag: the knowledge-base package — pluggable RAG over the identity stack.

Builds on ``user`` (accounts, RBAC, tokens, OAuth 2.1 provider) and
contributes the surface operators talk to: the document store, the
chunker / embedder / retriever / reranker / LLM plug-in points, the
upload + preview + index flow, the search endpoint, the chat endpoint.

What this package owns
----------------------

- The five RAG protocol shapes (``chunking.base``, ``embedding.base``,
  ``retrieval.base``, ``reranking.base``, ``llm.base``) and at least
  one offline implementation of each. Pluggable by name; default names
  ship.
- The ``rag_documents`` / ``rag_chunks`` / ``rag_chunk_embeddings``
  tables and a single Alembic chain (``alembic_version_rag``).
- Five ``rag:*`` permission codes, registered into the identity
  package's catalog at import. The seed's admin role automatically
  picks them up.
- The RAG-side audit wrapper (writes to the same ``audit_logs`` table
  the identity package owns, no ``ALTER TABLE``).
- The chat flow that composes retriever + reranker + LLM behind one
  POST.

What this package does NOT own
------------------------------

- Auth tokens (the identity package's ``auth_tokens`` table — there is
  no separate ``rag_tokens``), the ``Viewer`` dataclass, or any
  identity surface.
- The Postgres database itself: the same database the basic + user +
  mcp packages use; this package adds tables and a pgvector extension
  to it.
- An LLM SDK at runtime in the default path: the stub generator is the
  default, so the chat works end to end on a fresh ``make init`` with
  no API keys.

Public surface only; every name below is a plain import (no settings
reads, no engine, no app assembly — importing a package must never
have side effects; see ADR-0015 and ADR-0016).
"""

# Load-bearing import order, not a re-export to tidy up: importing this
# module registers the rag:* permission codes in the identity package's
# catalog, and every module below that calls require_perm() with one of
# those codes validates against the catalog when IT is imported. Python
# runs a parent package's __init__ before any of its submodules, so this
# is the one place that guarantees the registration happens first (the
# same pattern the mcp package uses for its mcp:* codes).
from cliver_playbook.app.rag import permissions  # noqa: F401
from cliver_playbook.app.rag.api.routes import ROUTERS
from cliver_playbook.app.rag.settings import Settings, get_settings, settings

__all__ = ["ROUTERS", "Settings", "get_settings", "settings"]
