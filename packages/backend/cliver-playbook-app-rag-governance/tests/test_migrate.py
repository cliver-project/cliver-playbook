"""The governance migration chain actually renders SQL.

The package's service tests build their schema from ORM metadata, so
they never execute ``alembic/env.py``. Offline mode is a cheap guard
for the failure mode that leaves env.py without its module-level
dispatch: if the dispatch is missing, no SQL is printed and ``upgrade
head`` silently creates nothing.
"""

from __future__ import annotations

from cliver_playbook.app.rag_governance.alembic import run_migrations_offline


def test_offline_migration_renders_the_governance_schema(capsys) -> None:
    run_migrations_offline("postgresql+psycopg://user:pass@127.0.0.1:5432/offline")

    sql = capsys.readouterr().out
    assert "alembic_version_rag_governance" in sql
    assert "CREATE TABLE gov_projects" in sql
    assert "CREATE TABLE gov_document_acl" in sql
    assert "CREATE TABLE gov_jobs" in sql
    assert "uq_gov_document_acl_grant" in sql
    assert "uq_gov_jobs_dedupe_key" in sql
    # No governance table may reference rag tables physically: the two
    # chains migrate independently.
    assert "REFERENCES rag_" not in sql
