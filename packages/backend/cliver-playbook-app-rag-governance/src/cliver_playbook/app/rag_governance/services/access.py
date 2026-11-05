"""Access control: effective clearance, document grants and the rag seam.

The rag package owns retrieval; it does not own identity. A composing
package therefore installs a scope resolver (ADR-0015): given the
authenticated caller and a collection, governance answers with the
caller's clearance and grants. When the collection does not belong to an
active governance project the resolver returns ``None`` and the rag
package keeps its v1 shared behaviour.

Grants are stored by ``logical_id`` so a new version of a document keeps
its explicit read grant across re-ingestion. A principal's effective
clearance is the maximum of their own level and every role they hold
(R9); a principal without any row has level 0.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope, register_scope_resolver
from cliver_playbook.app.rag_governance.models.entities import (
    GovDocumentAcl,
    GovPrincipalClearance,
    GovProject,
)

PrincipalType = Literal["user", "role"]

_READ = "read"


def _principal_pairs(viewer: Any) -> list[tuple[str, str]]:
    """The user and role identities the caller acts as."""
    pairs: list[tuple[str, str]] = [("user", str(getattr(viewer, "user_id", "")))]
    pairs.extend(("role", str(code)) for code in sorted(getattr(viewer, "role_codes", ())))
    return pairs


async def effective_clearance(db: AsyncSession, viewer: Any) -> int:
    """``max(user level, max(role levels))``; 0 when no row exists."""
    pairs = _principal_pairs(viewer)
    rows = await db.execute(
        select(GovPrincipalClearance.level).where(
            or_(
                *(
                    (GovPrincipalClearance.principal_type == kind)
                    & (GovPrincipalClearance.principal_id == principal_id)
                    for kind, principal_id in pairs
                )
            )
        )
    )
    return max((int(level) for level in rows.scalars()), default=0)


async def explicit_grants(db: AsyncSession, viewer: Any) -> frozenset[str]:
    """Logical ids granted to the caller or any of their roles."""
    pairs = _principal_pairs(viewer)
    rows = await db.execute(
        select(GovDocumentAcl.logical_id).where(
            GovDocumentAcl.permission == _READ,
            or_(
                *(
                    (GovDocumentAcl.principal_type == kind)
                    & (GovDocumentAcl.principal_id == principal_id)
                    for kind, principal_id in pairs
                )
            ),
        )
    )
    return frozenset(rows.scalars())


async def grant_document(
    db: AsyncSession,
    *,
    logical_id: str,
    principal_type: PrincipalType,
    principal_id: str,
    permission: str = _READ,
) -> GovDocumentAcl:
    """Create an explicit read grant; re-granting the same pair is a no-op."""
    existing = await db.scalar(
        select(GovDocumentAcl).where(
            GovDocumentAcl.logical_id == logical_id,
            GovDocumentAcl.principal_type == principal_type,
            GovDocumentAcl.principal_id == principal_id,
            GovDocumentAcl.permission == permission,
        )
    )
    if existing is not None:
        return existing
    grant = GovDocumentAcl(
        logical_id=logical_id,
        principal_type=principal_type,
        principal_id=principal_id,
        permission=permission,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return grant


async def _resolve_scope(
    viewer: Any, collection_id: str | None, db: AsyncSession
) -> AccessScope | None:
    """Governed scope for an active project; ``None`` otherwise."""
    if collection_id is None:
        return None
    project = await db.scalar(
        select(GovProject)
        .where(
            GovProject.collection_id == collection_id,
            GovProject.status == "active",
        )
        .limit(1)
    )
    if project is None:
        return None
    return AccessScope(
        collection_id=collection_id,
        clearance=await effective_clearance(db, viewer),
        grants=await explicit_grants(db, viewer),
        governed=True,
    )


async def register_governance_access_resolver() -> None:
    """Install the resolver the rag package calls for every read path."""
    register_scope_resolver(_resolve_scope)
