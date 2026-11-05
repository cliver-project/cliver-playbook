"""Collection access: the predicate every retrieval read path applies.

The v1 knowledge base was shared, so the only visibility rule was
"indexed". Governance needs more: a document's classification level,
explicit grants, and a staging flag that keeps unapproved versions out
of retrieval. Rather than fork the retrievers, the generic package
exposes this seam:

- ``AccessScope`` is the caller's request-scoped view.
- ``CollectionAccessPolicy.predicate(scope)`` turns it into a SQL
  expression the retrievers AND into every query.
- ``resolve_access_scope`` lets a composing package (governance) decide
  the scope from the caller's identity and the collection.

The default policy is deliberately fail-closed for governed scopes: a
document with a NULL classification is not public. Only an explicit
grant can expose an unlabelled document, so "forgot to classify" hides
data instead of leaking it.

``allow_staged`` is the one privileged bypass. It exists for the staged
preview endpoint, which is separately permission-gated; ordinary
search/chat/document reads never set it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Document


@dataclass(frozen=True)
class AccessScope:
    """The caller's visibility for one retrieval/read operation.

    ``governed`` selects the collection policy; an ungoverned scope
    keeps the v1 shared-knowledge-base behaviour. ``clearance`` and
    ``grants`` are only consulted when ``governed`` is true.
    ``allow_staged`` is reserved for the privileged staged-preview path.
    """

    collection_id: str | None = None
    clearance: int = 0
    grants: frozenset[str] = field(default_factory=frozenset)
    governed: bool = False
    allow_staged: bool = False


class CollectionAccessPolicy(Protocol):
    """Turns a scope into a SQLAlchemy predicate over ``Document``."""

    def predicate(self, scope: AccessScope) -> ColumnElement[bool]: ...


class DefaultCollectionAccessPolicy:
    """Published, not deleted, plus classification/grants when governed."""

    def predicate(self, scope: AccessScope) -> ColumnElement[bool]:
        clauses: list[ColumnElement[bool]] = []

        if scope.collection_id is not None:
            clauses.append(Document.collection_id == scope.collection_id)

        # Deleted rows are never visible. Publication is skipped only
        # for the privileged staged-preview path.
        clauses.append(Document.deleted_at.is_(None))
        if not scope.allow_staged:
            clauses.append(Document.published.is_(True))

        if scope.governed and not scope.allow_staged:
            # NULL classification is not public: the first conjunct is
            # load-bearing and must not be dropped as an optimization.
            visible = and_(
                Document.classification.is_not(None),
                Document.classification <= scope.clearance,
            )
            if scope.grants:
                visible = or_(visible, Document.logical_id.in_(scope.grants))
            clauses.append(visible)

        return and_(*clauses)


_DEFAULT_POLICY = DefaultCollectionAccessPolicy()
_governed_policy: CollectionAccessPolicy | None = None

# A composing package resolves the caller's identity into a scope. It
# returns None when the requested collection is not governed, which
# falls back to the v1 scope. The hook keeps identity knowledge in the
# package that owns it (ADR-0015).
ScopeResolver = Callable[[Any, str | None, AsyncSession], Awaitable[AccessScope | None]]
_scope_resolver: ScopeResolver | None = None


def register_governed_policy(policy: CollectionAccessPolicy) -> None:
    """Install the policy used for ``governed=True`` scopes.

    Idempotent for the same object; a different registration replaces
    the previous one, which keeps test setup and a re-imported module
    from accumulating policies.
    """
    global _governed_policy
    _governed_policy = policy


def policy_for(scope: AccessScope) -> CollectionAccessPolicy:
    """The policy for this scope (governed policy, else the default)."""
    if scope.governed and _governed_policy is not None:
        return _governed_policy
    return _DEFAULT_POLICY


def register_scope_resolver(resolver: ScopeResolver | None) -> None:
    """Install (or clear, with ``None``) the scope resolver hook."""
    global _scope_resolver
    _scope_resolver = resolver


async def resolve_access_scope(
    viewer: Any,
    collection_id: str | None,
    db: AsyncSession,
) -> AccessScope:
    """Resolve the effective scope for an API caller.

    The governance package registers a resolver that knows the caller's
    clearance and grants. Without one, this package keeps the v1 shared
    behaviour (optionally narrowed to one collection).
    """
    if _scope_resolver is not None:
        resolved = await _scope_resolver(viewer, collection_id, db)
        if resolved is not None:
            return resolved
    return AccessScope(collection_id=collection_id)
