"""Shared fixtures for the governance test suite.

Same two constraints as the rag suite:

- ``runtime.configure`` accepts exactly one Settings instance per
  process. Every test binds the SAME session-scoped object; a second,
  different instance raises.
- pytest-asyncio runs each test on a fresh event loop, and pooled
  async SQLite connections cannot cross loops. The database is a file
  under the session temp directory, and the engine is disposed after
  every test so the next one opens fresh connections.

The schema is dropped and recreated per test. That is cheap for SQLite
and stronger than delete-based cleanup: a new governance table cannot
silently leak rows between tests just because the cleanup list was not
updated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.models.entities import AppSetting
from cliver_playbook.app.rag.models import Base as RagBase
from cliver_playbook.app.rag_governance.app import create_app
from cliver_playbook.app.rag_governance.models import GovernanceBase
from cliver_playbook.app.rag_governance.settings import Settings
from cliver_playbook.app.user.auth.dependencies import Viewer, get_current_user
from cliver_playbook.app.user.auth.permissions import permission_codes

# Every governance permission, resolved from the live catalog so a new
# code does not silently start failing an unrelated API test.
_TEST_USER = Viewer(
    user_id=1,
    username="governance-tester",
    display_name="Governance Tester",
    must_change_password=False,
    permissions=frozenset(
        code for code in permission_codes() if code.startswith("rag_governance:")
    ),
)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """One Settings instance for the whole session."""
    db_path = tmp_path_factory.mktemp("gov-db") / "test.sqlite"
    return Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        rag={"embedder": "stub", "retriever": "bm25-only", "reranker": "noop"},
        rag_governance={
            # A retry is immediately claimable in tests, so a retry loop
            # does not have to sleep through the production backoff.
            "job_retry_backoff_seconds": 0,
        },
        _env_file=None,
    )


@pytest.fixture(autouse=True)
async def prepared_db(settings: Settings) -> AsyncIterator[None]:
    """Bind the runtime and give every test an empty schema."""
    runtime.configure(settings)
    async with runtime.engine().begin() as conn:
        await conn.run_sync(GovernanceBase.metadata.drop_all)
        await conn.run_sync(RagBase.metadata.drop_all)
        await conn.run_sync(AppSetting.__table__.drop, checkfirst=True)
        await conn.run_sync(GovernanceBase.metadata.create_all)
        await conn.run_sync(RagBase.metadata.create_all)
        await conn.run_sync(AppSetting.__table__.create, checkfirst=True)
    yield
    await runtime.dispose()


@pytest.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session on the process runtime's engine, closed after the test."""
    async with runtime.session_factory()() as session:
        yield session


@pytest.fixture()
async def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture()
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client whose caller holds every governance permission."""

    async def _fake_current_user() -> Viewer:
        return _TEST_USER

    app.dependency_overrides[get_current_user] = _fake_current_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
async def raw_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client with no authentication override (real gate)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
