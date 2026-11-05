"""The governance schema exists and pins the invariants services rely on.

Tables are created from ORM metadata on SQLite here; the migration test
covers the production DDL. Two invariants get an explicit assertion
because a later refactor could silently undo them:

- an ACL grant is keyed by ``logical_id``, never by the physical rag
  document id, so re-ingesting a document keeps its grant;
- a pending job carries a retry gate and a lease owner, which the
  runtime needs and which an additive migration would otherwise have
  to add later.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from cliver_playbook.app.rag_governance.models import GovernanceBase, GovProject


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    GovernanceBase.metadata.create_all(eng)
    yield eng
    GovernanceBase.metadata.drop_all(eng)
    eng.dispose()


def test_all_governance_tables_exist(engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert {
        "gov_projects",
        "gov_config_versions",
        "gov_sources",
        "gov_source_sync_state",
        "gov_tools",
        "gov_ingest_batches",
        "gov_golden_sets",
        "gov_golden_cases",
        "gov_intent_rules",
        "gov_eval_runs",
        "gov_eval_case_results",
        "gov_approvals",
        "gov_principal_clearance",
        "gov_document_acl",
        "gov_jobs",
    }.issubset(tables)


def test_tool_binding_columns_exist(engine) -> None:
    cols = {c["name"] for c in inspect(engine).get_columns("gov_tools")}
    assert {"min_clearance", "scope_json", "read_only", "permission_code"}.issubset(cols)


def test_acl_references_logical_id(engine) -> None:
    cols = {c["name"] for c in inspect(engine).get_columns("gov_document_acl")}
    assert "logical_id" in cols
    assert "document_id" not in cols


def test_job_runtime_columns_exist(engine) -> None:
    cols = {c["name"] for c in inspect(engine).get_columns("gov_jobs")}
    assert {"available_at", "worker_id", "attempts", "dedupe_key"}.issubset(cols)


def test_project_json_config_round_trips_on_sqlite(engine) -> None:
    """JSONB falls back to JSON on SQLite; the models must still work."""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            GovProject(
                slug="finance-kpi-demo",
                name="Finance KPI",
                collection_id="finance-kpi",
                config_json={"chunker": "parent-child"},
            )
        )
        session.commit()

    with Session() as session:
        project = session.query(GovProject).one()
        assert project.config_json == {"chunker": "parent-child"}
        assert project.approval_mode == "manual"
        assert project.status == "draft"
