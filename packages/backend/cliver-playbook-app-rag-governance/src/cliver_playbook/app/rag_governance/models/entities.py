"""Governance tables: projects, golden data, rules, evaluation and approval.

The tables answer four questions the generic RAG package deliberately
does not:

- **What is being governed?** ``gov_projects`` pins a collection, an
  approval mode and a versioned configuration. ``gov_config_versions``
  keeps every configuration revision instead of mutating one row.
- **What does the project know?** ``gov_sources`` records raw inputs
  (upload, directory, HTTP, MCP) and their authority; the sync state
  table keeps the incremental cursor and content-hash index.
- **How is it tested?** ``gov_golden_sets`` / ``gov_golden_cases`` hold
  versioned cases, ``gov_intent_rules`` the versioned routing rules,
  and the eval tables the immutable run history.
- **How does staged data become the knowledge base?** Ingest batches
  carry the review state machine; approvals are append-only decisions;
  document ACLs live by ``logical_id`` so a grant survives re-ingest.

JSONB is used for configuration and reports read as a unit. Columns
that are filtered or joined are typed. No governance table has a
foreign key into ``rag_*``: the two packages migrate independently and
a deployment may run rag without governance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cliver_playbook.app.rag_governance.models.base import GovernanceBase


def new_id() -> str:
    """A fresh UUID primary key. Application-side so both engines agree."""
    return str(uuid4())


class GovProject(GovernanceBase):
    """One governance project: a collection, an approval mode, a config."""

    __tablename__ = "gov_projects"
    __table_args__ = (UniqueConstraint("slug", name="uq_gov_projects_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # draft -> baseline_eval -> active; paused and archived are
    # operational states. No transition bypasses the rule activation
    # gate (Task 12).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    approval_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovConfigVersion(GovernanceBase):
    """An immutable configuration revision for a project."""

    __tablename__ = "gov_config_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_gov_config_versions_project_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovSource(GovernanceBase):
    """A raw-data input and how it is kept fresh.

    ``authority`` separates inputs that can be ingested as documents
    from snapshot feeds and live capability (tool) sources. An ERP
    endpoint whose values change intraday is normally a ``snapshot``
    source at best; a capability source is queried at request time and
    is never embedded.
    """

    __tablename__ = "gov_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    authority: Mapped[str] = mapped_column(
        String(32), nullable=False, default="document", server_default="document"
    )
    sync_schedule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    max_staleness_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovSourceSyncState(GovernanceBase):
    """The incremental cursor for one source.

    ``content_hash_index`` maps a document logical id to the content
    hash last ingested, so a full sync can skip unchanged documents
    instead of re-embedding the corpus.
    """

    __tablename__ = "gov_source_sync_state"

    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_sources.id", ondelete="CASCADE"), primary_key=True
    )
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="idle", server_default="idle"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash_index: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class GovTool(GovernanceBase):
    """A tool binding offered to the governance planner.

    The row is the policy, not the implementation: ``config_json``
    names the server/implementation and the allowlisted remote tool.
    Secrets are referenced by environment-variable name and never
    stored here. ``permission_code`` / ``min_clearance`` / ``scope_json``
    decide whether the tool is offered at all — the model never sees an
    unauthorized tool.
    """

    __tablename__ = "gov_tools"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_gov_tools_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    read_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    permission_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    min_clearance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    masking_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_cap_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    max_staleness_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovIngestBatch(GovernanceBase):
    """One ingestion run and its review state machine.

    The batch id is written to ``rag_documents.pipeline_run_id``; that
    is how staged previews find their rows and how approval publishes
    exactly this run's documents.
    """

    __tablename__ = "gov_ingest_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("gov_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued", index=True
    )
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    eval_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("gov_eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    submitted_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovGoldenSet(GovernanceBase):
    """A versioned collection of golden cases.

    A confirmed set is immutable; an edit forks it into a new candidate
    version. Evaluation runs keep pointing at the exact set they used.
    """

    __tablename__ = "gov_golden_sets"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_gov_golden_sets_project_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="llm", server_default="llm"
    )
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovGoldenCase(GovernanceBase):
    """One case row; ``payload_json`` is the full ``GoldenCase``.

    The case id is short and readable (``case-0001``) because it
    appears in evaluation reports and review comments. It is unique
    *within its set*, not globally: forking a confirmed set copies the
    same ids into the next version, and both versions must remain
    addressable. The composite primary key carries that scoping. The
    payload is validated by the golden schema at write time; the
    columns here are only the ones the server filters and orders by.
    """

    __tablename__ = "gov_golden_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    golden_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("gov_golden_sets.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovIntentRule(GovernanceBase):
    """A routing rule: intent -> scope + retrieval/tool strategy.

    ``strategy`` decides the runtime path: ``retrieval`` only,
    ``tools`` only, ``agentic`` (plan, call tools, then retrieve), or
    ``none`` (refuse with ``refusal_json``). ``scope_json`` is the
    filter AST applied to retrieval and to tool binding.
    """

    __tablename__ = "gov_intent_rules"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "intent", "version", name="uq_gov_intent_rules_project_intent_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    intent: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    classifier_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    strategy: Mapped[str] = mapped_column(
        String(16), nullable=False, default="retrieval", server_default="retrieval"
    )
    tools_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    snapshot_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    refusal_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", server_default="proposed", index=True
    )
    eval_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("gov_eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovEvalRun(GovernanceBase):
    """An immutable evaluation run over one golden set."""

    __tablename__ = "gov_eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    golden_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_golden_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(
        String(16), nullable=False, default="baseline", server_default="baseline"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued", index=True
    )
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovEvalCaseResult(GovernanceBase):
    """Per-case outcome. ``case_id`` is a value, not a FK: a run must
    stay reproducible even after its golden set has been archived."""

    __tablename__ = "gov_eval_case_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gov_eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class GovApproval(GovernanceBase):
    """An append-only approval decision for an ingest batch."""

    __tablename__ = "gov_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("gov_ingest_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovPrincipalClearance(GovernanceBase):
    """The clearance level of a user or role.

    The pair is the primary key, so a principal has exactly one level
    and an upsert is unambiguous. A user's effective clearance is the
    maximum of their own level and every role they hold.
    """

    __tablename__ = "gov_principal_clearance"

    principal_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class GovDocumentAcl(GovernanceBase):
    """An explicit read grant on a logical document.

    Grants live by ``logical_id``, never by the physical rag document
    id, so a new version of the same document keeps the grant. The
    retrieval access predicate consumes these logical ids as its
    ``grants`` set.
    """

    __tablename__ = "gov_document_acl"
    __table_args__ = (
        UniqueConstraint(
            "logical_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_gov_document_acl_grant",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    logical_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(
        String(32), nullable=False, default="read", server_default="read"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovJob(GovernanceBase):
    """A durable queued job.

    ``dedupe_key`` makes enqueue idempotent: two identical requests
    return the same row. ``available_at`` is the retry backoff gate;
    ``worker_id`` records the current lease. A job whose worker died
    while ``running`` is reclaimed by the worker after the lease
    expires (Task 8).
    """

    __tablename__ = "gov_jobs"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_gov_jobs_dedupe_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued", index=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
