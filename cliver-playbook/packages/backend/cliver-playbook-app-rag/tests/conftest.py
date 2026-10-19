"""Shared fixtures for the RAG HTTP surface tests.

Two constraints shape this file:

- ``runtime.configure`` accepts exactly one Settings instance per
  process (a second, different instance raises). Every test therefore
  builds its FastAPI app with the SAME session-scoped Settings object;
  ``create_app`` re-binding the same instance is a documented no-op.

- pytest-asyncio gives each test its own event loop, and pooled
  async SQLite connections cannot cross loops. The database is
  therefore a file under the session temp directory (not ``:memory:``):
  connections are recreated per test, the schema survives, and a
  function-scoped fixture truncates the three RAG tables so cases do
  not leak rows into each other.

Auth is bypassed through FastAPI's dependency override mechanism: the
permission chain (``require_perm`` -> ``get_current_user``) resolves
through the overridden callable. The ``raw_client`` fixture skips the
override and exercises the real 401 path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.models.entities import AppSetting
from cliver_playbook.app.basic.runtime_settings import settings_sections
from cliver_playbook.app.rag.app import create_app
from cliver_playbook.app.rag.models import Base
from cliver_playbook.app.rag.settings import Settings
from cliver_playbook.app.user.auth.dependencies import Viewer, get_current_user

# The fake caller holds every permission the module registers, so a
# route gated by a new rag:* code does not silently start failing for
# an unrelated reason. A dedicated test asserts the 401 path instead.
_TEST_USER = Viewer(
    user_id=1,
    username="tester",
    display_name="RAG Tester",
    must_change_password=False,
    permissions=frozenset(
        {
            "rag:documents:read",
            "rag:documents:write",
            "rag:search:read",
            "rag:chat:read",
            # The runtime-settings surface is registered by the identity
            # package; the RAG suite exercises the RAG-owned section through
            # the same admin API a composed app serves.
            "settings:read",
            "settings:manage",
        }
    ),
)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """One Settings instance for the whole session (see module docstring)."""
    db_path = tmp_path_factory.mktemp("rag-db") / "test.sqlite"
    return Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        # The production retriever speaks pgvector SQL and the
        # production reranker downloads weights; SQLite tests pin the
        # offline-safe stages so the HTTP surface stays exercisable
        # without Postgres or model downloads.
        rag={"embedder": "stub", "retriever": "bm25-only", "reranker": "noop"},
        # Disable the .env layer: a developer machine's project .env may
        # carry real deployment values, and tests must not read them.
        _env_file=None,
    )


@pytest.fixture()
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    """The assembled application with an empty RAG schema."""
    application = create_app(settings)
    async with runtime.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ``AppSetting`` belongs to the basic package's metadata, not the RAG
        # Base; create its table explicitly so the settings API works on the
        # SQLite fixture without running the basic migration chain.
        await conn.run_sync(AppSetting.__table__.create, checkfirst=True)
        # Child rows first; SQLite does not enforce ON DELETE CASCADE
        # unless the pragma is enabled, and explicit deletes keep the
        # fixture independent of connection settings.
        await conn.execute(text("DELETE FROM rag_chunk_embeddings"))
        await conn.execute(text("DELETE FROM rag_chunks"))
        await conn.execute(text("DELETE FROM rag_documents"))
        await conn.execute(text("DELETE FROM app_settings"))
    # Restore the startup configuration: a previous test may have exercised
    # the settings API, and the Settings instance is session-scoped.
    baseline = runtime.baseline_settings()
    if baseline is not None:
        for section in settings_sections():
            section.apply(settings, section.read(baseline))
    yield application
    await runtime.dispose()


@pytest.fixture()
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client whose caller is authenticated with all rag:* perms."""

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
