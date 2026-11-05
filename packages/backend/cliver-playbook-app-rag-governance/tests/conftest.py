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

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

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
from cliver_playbook.app.rag_governance.testing.mock_kingdee import MockKingdeeServer
from cliver_playbook.app.user.auth.dependencies import Viewer, get_current_user
from cliver_playbook.app.user.auth.permissions import permission_codes

KINGDEE_CONTRACT = Path(__file__).parent / "fixtures" / "kingdee" / "contract"
KINGDEE_PERIOD_END = "2026-10-31T23:59:59+08:00"

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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def mock_kingdee_server(tmp_path: Path) -> MockKingdeeServer:
    """One deterministic closed period: 2026-10, four fixture files."""
    period = tmp_path / "kingdee" / "2026-10"
    period.mkdir(parents=True)
    _write_json(
        period / "period.json",
        {
            "period": "2026-10",
            "period_end": KINGDEE_PERIOD_END,
            "closed": True,
            "currency": "CNY",
        },
    )
    _write_json(
        period / "gl_account_balance.json",
        [
            {
                "FBALANCEID": "1001",
                "FBALANCENAME": "库存现金",
                "FDEBIT": 0.0,
                "FCREDIT": 0.0,
                "FENDDEBIT": 125000.0,
                "FENDCREDIT": 0.0,
            },
            {
                "FBALANCEID": "1122",
                "FBALANCENAME": "应收账款",
                "FDEBIT": 8650000.0,
                "FCREDIT": 0.0,
                "FENDDEBIT": 8650000.0,
                "FENDCREDIT": 0.0,
            },
            {
                "FBALANCEID": "2202",
                "FBALANCENAME": "应付账款",
                "FDEBIT": 0.0,
                "FCREDIT": 4320000.0,
                "FENDDEBIT": 0.0,
                "FENDCREDIT": 4320000.0,
            },
        ],
    )
    _write_json(
        period / "ar_aging_rows.json",
        [
            {"FCUSTOMERID": "C001", "FAGINGBUCKET": "0-30", "FENDAMOUNTFOR": 1200000.0},
            {"FCUSTOMERID": "C002", "FAGINGBUCKET": "31-60", "FENDAMOUNTFOR": 450000.0},
        ],
    )
    _write_json(
        period / "receipts.json",
        [
            {
                "FID": "R001",
                "FBillNo": "SK202610001",
                "FDATE": "2026-10-18",
                "FCUSTOMERID.FName": "华力电子",
                "FALLAMOUNTFOR": 3000000.0,
            }
        ],
    )
    _write_json(
        period / "partners_BD_Customer.json",
        [{"FNumber": "C001", "FName": "华力电子", "FContact": "王经理"}],
    )
    _write_json(
        period / "partners_BD_Supplier.json",
        [{"FNumber": "S001", "FName": "华南材料", "FContact": "李经理"}],
    )
    _write_json(
        period / "fields_GL_RPT_AccountBalance.json",
        {
            "form_id": "GL_RPT_AccountBalance",
            "fields": ["FBALANCEID", "FBALANCENAME", "FDEBIT", "FCREDIT"],
        },
    )
    _write_json(
        period / "bills_PUR_PurchaseOrder.json",
        [{"FID": "P001", "FBillNo": "CGDD202610001", "FDocumentStatus": "C"}],
    )
    _write_json(
        period / "forms.json",
        [
            {"form_id": "PUR_PurchaseOrder", "name": "Purchase Order"},
            {"form_id": "GL_RPT_AccountBalance", "name": "Account Balance Report"},
        ],
    )
    return MockKingdeeServer(tmp_path / "kingdee")
