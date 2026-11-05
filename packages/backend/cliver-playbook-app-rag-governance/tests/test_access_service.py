"""Access service: clearance, grants and the rag scope resolver."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import register_scope_resolver, resolve_access_scope
from cliver_playbook.app.rag_governance.models import (
    GovDocumentAcl,
    GovPrincipalClearance,
    GovProject,
)
from cliver_playbook.app.rag_governance.services.access import (
    effective_clearance,
    explicit_grants,
    grant_document,
    register_governance_access_resolver,
)
from cliver_playbook.app.rag_governance.services.projects import create_project
from cliver_playbook.app.user.auth.dependencies import Viewer


def _viewer(*, user_id: int = 1, roles: frozenset[str] = frozenset()) -> Viewer:
    return Viewer(
        user_id=user_id,
        username=f"user-{user_id}",
        display_name="Test User",
        must_change_password=False,
        role_codes=roles,
    )


@pytest.fixture(autouse=True)
async def reset_resolver() -> AsyncIterator[None]:
    yield
    register_scope_resolver(None)


async def _levels(db: AsyncSession, rows: list[tuple[str, str, int]]) -> None:
    db.add_all(
        GovPrincipalClearance(principal_type=kind, principal_id=principal, level=level)
        for kind, principal, level in rows
    )
    await db.commit()


async def test_effective_clearance_is_the_max_of_user_and_roles(
    db_session: AsyncSession,
) -> None:
    await _levels(
        db_session,
        [
            ("user", "1", 2),
            ("role", "finance", 4),
            ("role", "auditor", 3),
        ],
    )

    clearance = await effective_clearance(
        db_session, _viewer(roles=frozenset({"finance", "auditor"}))
    )

    assert clearance == 4


async def test_a_principal_without_rows_has_level_zero(
    db_session: AsyncSession,
) -> None:
    assert await effective_clearance(db_session, _viewer(user_id=99)) == 0


async def test_explicit_grants_cover_the_user_and_every_role(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            GovDocumentAcl(
                logical_id="fin-exec-compensation",
                principal_type="user",
                principal_id="1",
            ),
            GovDocumentAcl(
                logical_id="fin-board-minutes",
                principal_type="role",
                principal_id="finance",
            ),
            GovDocumentAcl(
                logical_id="fin-unrelated",
                principal_type="role",
                principal_id="auditor",
            ),
        ]
    )
    await db_session.commit()

    grants = await explicit_grants(db_session, _viewer(roles=frozenset({"finance"})))

    assert grants == frozenset({"fin-exec-compensation", "fin-board-minutes"})


async def test_granting_twice_is_idempotent(db_session: AsyncSession) -> None:
    first = await grant_document(
        db_session,
        logical_id="fin-exec-compensation",
        principal_type="user",
        principal_id="1",
    )
    second = await grant_document(
        db_session,
        logical_id="fin-exec-compensation",
        principal_type="user",
        principal_id="1",
    )

    assert first.id == second.id


async def test_resolver_returns_a_governed_scope_for_an_active_project(
    db_session: AsyncSession,
) -> None:
    project = await create_project(
        db_session,
        slug=f"finance-{uuid4().hex[:8]}",
        name="Finance KPI",
    )
    project.status = "active"
    await _levels(db_session, [("user", "1", 2)])
    await grant_document(
        db_session,
        logical_id="fin-exec-compensation",
        principal_type="role",
        principal_id="finance",
    )
    await db_session.commit()
    await register_governance_access_resolver()

    scope = await resolve_access_scope(
        _viewer(roles=frozenset({"finance"})), project.collection_id, db_session
    )

    assert scope.governed is True
    assert scope.collection_id == project.collection_id
    assert scope.clearance == 2
    assert scope.grants == frozenset({"fin-exec-compensation"})
    assert scope.allow_staged is False


async def test_resolver_leaves_other_collections_ungoverned(
    db_session: AsyncSession,
) -> None:
    await register_governance_access_resolver()

    scope = await resolve_access_scope(_viewer(), "shared-knowledge", db_session)

    assert scope.governed is False
    assert scope.collection_id == "shared-knowledge"


async def test_resolver_does_not_govern_a_draft_project(
    db_session: AsyncSession,
) -> None:
    project = await create_project(
        db_session,
        slug=f"finance-{uuid4().hex[:8]}",
        name="Finance KPI",
    )
    await register_governance_access_resolver()

    scope = await resolve_access_scope(_viewer(), project.collection_id, db_session)

    assert scope.governed is False


async def test_resolver_returns_default_scope_without_a_collection(
    db_session: AsyncSession,
) -> None:
    await register_governance_access_resolver()

    scope = await resolve_access_scope(_viewer(), None, db_session)

    assert scope.governed is False
    assert scope.collection_id is None


async def test_active_project_lookup_is_by_collection_id(
    db_session: AsyncSession,
) -> None:
    project = await create_project(
        db_session,
        slug=f"finance-{uuid4().hex[:8]}",
        name="Finance KPI",
        collection_id="fin-collection",
    )
    project.status = "active"
    await db_session.commit()
    await register_governance_access_resolver()

    scope = await resolve_access_scope(_viewer(), "fin-collection", db_session)

    assert scope.governed is True
    assert scope.collection_id == "fin-collection"
    stored = await db_session.get(GovProject, project.id)
    assert stored.collection_id == "fin-collection"
