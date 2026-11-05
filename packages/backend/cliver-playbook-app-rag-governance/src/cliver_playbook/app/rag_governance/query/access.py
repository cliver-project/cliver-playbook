"""Access scope and tool authorization for a governed query.

The query facade needs two related checks before it does any work:

- **Corpus access.** Which documents and chunks may this caller see? The
  service layer answers with clearance and grants, which become an
  ``AccessScope`` the generic retriever turns into a SQL predicate.
- **Tool access.** Which tool bindings may this caller even see? A tool
  that fails ``permission_code``, ``min_clearance`` or ``scope_json`` is
  never handed to the planner, so the model cannot select it.

Both checks are fail-closed. A missing permission set, a missing scope
attribute, an unlabelled document and a disabled or writable tool all
deny. Scope attributes are read from the viewer's explicit ``scopes``
mapping when present; otherwise a same-named viewer attribute is used.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope
from cliver_playbook.app.rag_governance.models.entities import GovProject, GovTool
from cliver_playbook.app.rag_governance.services.access import (
    effective_clearance,
    explicit_grants,
)


async def governed_scope(
    db: AsyncSession,
    project: GovProject,
    viewer: Any,
) -> AccessScope:
    """The caller's visibility inside one project's collection.

    The project is explicit, so this does not need the registry resolver
    (which only governs *active* projects). Evaluation runs a draft or
    baseline project before activation and still needs the predicate.
    """
    return AccessScope(
        collection_id=project.collection_id,
        clearance=await effective_clearance(db, viewer),
        grants=await explicit_grants(db, viewer),
        governed=True,
    )


def _holds_permission(viewer: Any, code: str) -> bool:
    has = getattr(viewer, "has", None)
    if callable(has):
        return bool(has(code))
    return code in frozenset(getattr(viewer, "permissions", ()))


def _scope_value(viewer: Any, key: str) -> Any:
    scopes = getattr(viewer, "scopes", None)
    if isinstance(scopes, Mapping):
        return scopes.get(key)
    return getattr(viewer, key, None)


def scope_matches(required: Mapping[str, Any], viewer: Any) -> bool:
    """True when every declared scope attribute matches the viewer.

    An empty requirement matches everyone. A requirement key the viewer
    does not carry does **not** match: an unconfigured caller must not
    inherit an unrestricted tool by accident.
    """
    for key, expected in required.items():
        if _scope_value(viewer, key) != expected:
            return False
    return True


def tool_authorized(tool: GovTool, *, viewer: Any, access: AccessScope) -> bool:
    """Whether this caller may see and invoke the tool binding at all."""
    if not tool.enabled or not tool.read_only:
        return False
    if tool.permission_code and not _holds_permission(viewer, tool.permission_code):
        return False
    if int(tool.min_clearance or 0) > access.clearance:
        return False
    return scope_matches(dict(tool.scope_json or {}), viewer)
