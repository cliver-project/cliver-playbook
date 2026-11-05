"""Initial governance schema.

Revision ID: 0001_rag_governance_initial
Revises:
Create Date: 2026-11-05

Creates the full ``gov_*`` schema described in the design's §6.2. The
chain is intentionally independent of the rag chain: no governance
table has a foreign key into ``rag_*``, so this migration can run on a
database where rag has not been applied. ``migrate.run_all_migrations``
applies rag first because the application queries both.

Downgrade drops tables in reverse dependency order; the schema keeps no
cross-chain objects other than the version table Alembic manages.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_rag_governance_initial"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "gov_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("approval_mode", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("collection_id", sa.String(64), nullable=False),
        sa.Column(
            "config_json",
            postgresql.JSONB,
            nullable=False,
        ),
        sa.Column("active_config_version", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        *_timestamps(),
        sa.UniqueConstraint("slug", name="uq_gov_projects_slug"),
    )

    op.create_table(
        "gov_config_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("config_json", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("project_id", "version", name="uq_gov_config_versions_project_version"),
    )
    op.create_index("ix_gov_config_versions_project_id", "gov_config_versions", ["project_id"])

    op.create_table(
        "gov_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("config_json", postgresql.JSONB, nullable=False),
        sa.Column("authority", sa.String(32), nullable=False, server_default="document"),
        sa.Column("sync_schedule", sa.String(64), nullable=True),
        sa.Column("sync_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("max_staleness_seconds", sa.Integer, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_gov_sources_project_id", "gov_sources", ["project_id"])

    op.create_table(
        "gov_source_sync_state",
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("gov_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("cursor", sa.String(512), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("content_hash_index", postgresql.JSONB, nullable=False),
    )

    op.create_table(
        "gov_tools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("config_json", postgresql.JSONB, nullable=False),
        sa.Column("schema_json", postgresql.JSONB, nullable=False),
        sa.Column("read_only", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("permission_code", sa.String(128), nullable=True),
        sa.Column("min_clearance", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scope_json", postgresql.JSONB, nullable=False),
        sa.Column("masking_json", postgresql.JSONB, nullable=False),
        sa.Column("result_cap_json", postgresql.JSONB, nullable=False),
        sa.Column("max_staleness_seconds", sa.Integer, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "name", name="uq_gov_tools_project_name"),
    )
    op.create_index("ix_gov_tools_project_id", "gov_tools", ["project_id"])

    op.create_table(
        "gov_golden_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("source", sa.String(16), nullable=False, server_default="llm"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("confirmed_by", sa.String(64), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "version", name="uq_gov_golden_sets_project_version"),
    )
    op.create_index("ix_gov_golden_sets_project_id", "gov_golden_sets", ["project_id"])

    op.create_table(
        "gov_golden_cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "golden_set_id",
            sa.String(36),
            sa.ForeignKey("gov_golden_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        *_timestamps(),
    )
    op.create_index("ix_gov_golden_cases_golden_set_id", "gov_golden_cases", ["golden_set_id"])

    op.create_table(
        "gov_eval_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "golden_set_id",
            sa.String(36),
            sa.ForeignKey("gov_golden_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_version", sa.Integer, nullable=True),
        sa.Column("stage", sa.String(16), nullable=False, server_default="baseline"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("metrics_json", postgresql.JSONB, nullable=False),
        sa.Column("report_json", postgresql.JSONB, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_gov_eval_runs_project_id", "gov_eval_runs", ["project_id"])
    op.create_index("ix_gov_eval_runs_golden_set_id", "gov_eval_runs", ["golden_set_id"])
    op.create_index("ix_gov_eval_runs_status", "gov_eval_runs", ["status"])

    op.create_table(
        "gov_eval_case_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("gov_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("details_json", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_gov_eval_case_results_run_id", "gov_eval_case_results", ["run_id"])
    op.create_index("ix_gov_eval_case_results_case_id", "gov_eval_case_results", ["case_id"])

    op.create_table(
        "gov_ingest_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("gov_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stats_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "eval_run_id",
            sa.String(36),
            sa.ForeignKey("gov_eval_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("submitted_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_gov_ingest_batches_project_id", "gov_ingest_batches", ["project_id"])
    op.create_index("ix_gov_ingest_batches_source_id", "gov_ingest_batches", ["source_id"])
    op.create_index("ix_gov_ingest_batches_status", "gov_ingest_batches", ["status"])

    op.create_table(
        "gov_intent_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("gov_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("intent", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("classifier_json", postgresql.JSONB, nullable=False),
        sa.Column("scope_json", postgresql.JSONB, nullable=False),
        sa.Column("retrieval_json", postgresql.JSONB, nullable=False),
        sa.Column("strategy", sa.String(16), nullable=False, server_default="retrieval"),
        sa.Column("tools_json", postgresql.JSONB, nullable=False),
        sa.Column("snapshot_fallback", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("refusal_json", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column(
            "eval_run_id",
            sa.String(36),
            sa.ForeignKey("gov_eval_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        *_timestamps(),
        sa.UniqueConstraint(
            "project_id", "intent", "version", name="uq_gov_intent_rules_project_intent_version"
        ),
    )
    op.create_index("ix_gov_intent_rules_project_id", "gov_intent_rules", ["project_id"])
    op.create_index("ix_gov_intent_rules_status", "gov_intent_rules", ["status"])

    op.create_table(
        "gov_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("gov_ingest_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_gov_approvals_batch_id", "gov_approvals", ["batch_id"])

    op.create_table(
        "gov_principal_clearance",
        sa.Column("principal_type", sa.String(16), primary_key=True),
        sa.Column("principal_id", sa.String(64), primary_key=True),
        sa.Column("level", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "gov_document_acl",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("logical_id", sa.String(128), nullable=False),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("principal_id", sa.String(64), nullable=False),
        sa.Column("permission", sa.String(32), nullable=False, server_default="read"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "logical_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_gov_document_acl_grant",
        ),
    )
    op.create_index("ix_gov_document_acl_logical_id", "gov_document_acl", ["logical_id"])
    op.create_index("ix_gov_document_acl_principal_id", "gov_document_acl", ["principal_id"])

    op.create_table(
        "gov_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("progress_json", postgresql.JSONB, nullable=False),
        sa.Column("result_json", postgresql.JSONB, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dedupe_key", sa.String(128), nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("dedupe_key", name="uq_gov_jobs_dedupe_key"),
    )
    op.create_index("ix_gov_jobs_project_id", "gov_jobs", ["project_id"])
    op.create_index("ix_gov_jobs_kind", "gov_jobs", ["kind"])
    op.create_index("ix_gov_jobs_status", "gov_jobs", ["status"])
    op.create_index("ix_gov_jobs_available_at", "gov_jobs", ["available_at"])


def downgrade() -> None:
    op.drop_table("gov_jobs")
    op.drop_table("gov_document_acl")
    op.drop_table("gov_principal_clearance")
    op.drop_table("gov_approvals")
    op.drop_table("gov_intent_rules")
    op.drop_table("gov_ingest_batches")
    op.drop_table("gov_eval_case_results")
    op.drop_table("gov_eval_runs")
    op.drop_table("gov_golden_cases")
    op.drop_table("gov_golden_sets")
    op.drop_table("gov_tools")
    op.drop_table("gov_source_sync_state")
    op.drop_table("gov_sources")
    op.drop_table("gov_config_versions")
    op.drop_table("gov_projects")
