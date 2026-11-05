"""Governance permission codes, registered into the identity catalog.

The codes are split along the workflow they gate, not along resource
type alone: drafting a golden dataset, running the evaluation, approving
a batch and previewing staged (unapproved) data are distinct
capabilities. In particular ``staged:read`` is separate from
``project:read`` because seeing unapproved data is exactly the
capability the approval gate withholds from ordinary readers.
"""

from __future__ import annotations

from cliver_playbook.app.user.auth.permissions import Permission, register_permission_codes

_PERMISSIONS: tuple[Permission, ...] = (
    Permission(
        code="rag_governance:project:read",
        name="View governance projects",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:project:write",
        name="Create and edit governance projects",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:source:write",
        name="Manage sources and trigger ingestion",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:golden:read",
        name="View golden datasets",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:golden:write",
        name="Edit, import and confirm golden datasets",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:rule:read",
        name="View intent rules",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:rule:write",
        name="Edit and activate intent rules",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:eval:read",
        name="View evaluation runs",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:eval:run",
        name="Run evaluations",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:approve",
        name="Approve or reject staged batches",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:staged:read",
        name="Preview unapproved staged documents",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:tool:read",
        name="View tool bindings",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:tool:write",
        name="Create and edit tool bindings",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:job:read",
        name="View background jobs",
        group="rag-governance",
    ),
    Permission(
        code="rag_governance:query:read",
        name="Ask governed questions",
        group="rag-governance",
    ),
)

register_permission_codes(_PERMISSIONS)
