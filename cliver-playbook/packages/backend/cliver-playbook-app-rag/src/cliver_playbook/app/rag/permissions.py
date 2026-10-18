"""RAG permission codes (registered into the identity package's catalog).

Four codes, all in the ``rag`` group. The admin role seeded by the
identity package's migration automatically picks them up (the admin
role holds every catalog code), so a fresh project that enables
the rag package gets full admin coverage for free; operators can
then build a narrower role for end users (typically
``rag:documents:read`` + ``rag:search:read`` + ``rag:chat:read``)
and grant it explicitly.

Deliberately no ``rag:admin:read``: v1 has no multi-tenant ownership,
so every document read is already shared by all readers. A separate
admin code would gate nothing (ADR-0018 records the four-code set).

The mcp package's permission codes are loaded into the same catalog
the same way; the only constraint is that the parent package's
__init__ must import this module BEFORE any module that calls
``require_perm()`` with one of these codes — Python's package
import order makes this load-bearing by construction.
"""

from __future__ import annotations

from cliver_playbook.app.user.auth.permissions import Permission, register_permission_codes

_PERMISSIONS: tuple[Permission, ...] = (
    Permission(
        code="rag:documents:read",
        name="Read RAG documents",
        group="rag",
    ),
    Permission(
        code="rag:documents:write",
        name="Upload and index RAG documents",
        group="rag",
    ),
    Permission(
        code="rag:search:read",
        name="Run RAG search",
        group="rag",
    ),
    Permission(
        code="rag:chat:read",
        name="Run RAG chat",
        group="rag",
    ),
)

register_permission_codes(_PERMISSIONS)
