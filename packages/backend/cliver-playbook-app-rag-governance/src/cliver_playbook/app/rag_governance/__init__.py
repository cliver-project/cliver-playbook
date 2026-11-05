"""rag_governance: a reusable governance loop over the RAG stack.

The package owns the project lifecycle (golden dataset, intent rules,
evaluation, staged ingestion, approval, publication), the governed tool
contract, and the query facade that combines document retrieval with
live read-only tools. Documents, chunks, embeddings and retrieval stay
owned by ``cliver-playbook-app-rag``.

Public surface only; importing the package must not read settings, open
an engine, or assemble an app.
"""

# Load-bearing import order (same reason as the rag and mcp packages):
# importing this module registers the rag_governance:* permission codes
# and the rag_governance settings section before any router module that
# calls require_perm() with one of those codes is imported.
from cliver_playbook.app.rag_governance import permissions, settings_section  # noqa: F401
from cliver_playbook.app.rag_governance.api.routes import ROUTERS
from cliver_playbook.app.rag_governance.settings import Settings, get_settings, settings

__all__ = ["ROUTERS", "Settings", "get_settings", "settings"]
