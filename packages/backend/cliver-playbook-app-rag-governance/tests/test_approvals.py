"""Approval gates and the publish transition."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag_governance.golden import (
    GoldenCase,
    confirm_set,
    create_candidate_set,
)
from cliver_playbook.app.rag_governance.models import (
    GovEvalRun,
    GovGoldenSet,
    GovIngestBatch,
    GovProject,
)
from cliver_playbook.app.rag_governance.services.approvals import (
    ApprovalBlockedError,
    ApprovalValidationError,
    decide,
    publish_batch,
)
from cliver_playbook.app.rag_governance.services.batches import create_batch
from cliver_playbook.app.rag_governance.services.projects import create_project


def _doc(
    *,
    project: GovProject,
    batch: GovIngestBatch,
    logical_id: str = "fin-metric-catalog",
    classification: int | None = 0,
    version: int = 1,
    published: bool = False,
    document_id: str | None = None,
) -> Document:
    return Document(
        id=document_id or f"doc-{uuid4().hex}",
        title="Finance metric catalog",
        source_uri="fin-metric-catalog.md",
        mime_type="text/markdown",
        chunker_id="parent-child",
        chunker_config={},
        embedder_id="stub@1.0",
        dim=64,
        version=version,
        status="indexed",
        chunk_count=1,
        logical_id=logical_id,
        classification=classification,
        collection_id=project.collection_id,
        published=published,
        pipeline_run_id=batch.id,
    )


async def _golden_set(db: AsyncSession, project: GovProject) -> GovGoldenSet:
    candidate = await create_candidate_set(
        db,
        project.id,
        [
            GoldenCase.model_validate(
                {
                    "id": "case-0001",
                    "question": "What was the revenue?",
                    "expected_intent": "financial_overview",
                }
            )
        ],
        actor="tester",
    )
    return await confirm_set(db, candidate.id, actor="reviewer")


async def _setup(
    db: AsyncSession,
    *,
    approval_mode: str = "manual",
    classification: int | None = 0,
    eval_status: str = "passed",
    hard_gates: list[str] | None = None,
    threshold_failures: list[str] | None = None,
    with_eval: bool = True,
) -> tuple[GovProject, GovIngestBatch, Document]:
    project = await create_project(
        db,
        slug=f"finance-{uuid4().hex[:8]}",
        name="Finance KPI",
        approval_mode=approval_mode,
    )
    batch = await create_batch(db, project, None, submitted_by="ingest-worker")
    batch.status = "review_pending"
    document = _doc(project=project, batch=batch, classification=classification)
    db.add(document)

    if with_eval:
        golden_set = await _golden_set(db, project)
        run = GovEvalRun(
            project_id=project.id,
            golden_set_id=golden_set.id,
            status=eval_status,
            metrics_json={"retrieval.recall": 0.7},
            report_json={
                "hard_gate_violations": list(hard_gates or []),
                "threshold_failures": list(threshold_failures or []),
            },
        )
        db.add(run)
        await db.flush()
        batch.eval_run_id = run.id

    await db.commit()
    await db.refresh(batch)
    return project, batch, document


async def test_manual_approval_publishes_the_batch(db_session: AsyncSession) -> None:
    project, batch, document = await _setup(db_session)

    approval = await decide(db_session, batch, decision="approve", actor="approver", comment="ok")

    assert approval.decision == "approve"
    stored_batch = await db_session.get(GovIngestBatch, batch.id)
    assert stored_batch.status == "published"
    assert stored_batch.approved_by == "approver"
    stored_doc = await db_session.get(Document, document.id)
    assert stored_doc.published is True
    stored_project = await db_session.get(GovProject, project.id)
    assert stored_project.status == "active"


async def test_rejection_keeps_documents_staged(db_session: AsyncSession) -> None:
    project, batch, document = await _setup(db_session)

    approval = await decide(
        db_session, batch, decision="reject", actor="approver", comment="bad figures"
    )

    assert approval.decision == "reject"
    assert (await db_session.get(GovIngestBatch, batch.id)).status == "rejected"
    assert (await db_session.get(Document, document.id)).published is False
    assert (await db_session.get(GovProject, project.id)).status == "draft"


async def test_rejection_requires_a_comment(db_session: AsyncSession) -> None:
    _, batch, _ = await _setup(db_session)

    with pytest.raises(ApprovalValidationError):
        await decide(db_session, batch, decision="reject", actor="approver", comment=" ")


async def test_publish_never_leaves_two_published_versions(
    db_session: AsyncSession,
) -> None:
    project, _batch_v1, old = await _setup(db_session)
    old.published = True
    await db_session.commit()

    batch_v2 = await create_batch(db_session, project, None)
    db_session.add(_doc(project=project, batch=batch_v2, version=2, document_id="doc-v2"))
    await db_session.flush()

    await publish_batch(db_session, batch_v2)

    rows = (
        (
            await db_session.execute(
                select(Document).where(Document.logical_id == "fin-metric-catalog")
            )
        )
        .scalars()
        .all()
    )
    published = [row for row in rows if row.published]
    assert [row.id for row in published] == ["doc-v2"]


async def test_hard_gate_cannot_be_overridden(db_session: AsyncSession) -> None:
    _, batch, document = await _setup(
        db_session,
        eval_status="failed",
        hard_gates=["case-0005/access-leak: fin-exec-compensation"],
    )

    with pytest.raises(ApprovalBlockedError, match="hard gates failed"):
        await decide(
            db_session,
            batch,
            decision="approve",
            actor="approver",
            comment="override please",
        )

    assert (await db_session.get(Document, document.id)).published is False


async def test_soft_failures_require_a_comment_and_record_the_override(
    db_session: AsyncSession,
) -> None:
    _, batch, _ = await _setup(
        db_session,
        eval_status="failed",
        threshold_failures=["intent.pass_rate=0.500 is below 0.900"],
    )

    with pytest.raises(ApprovalValidationError, match="requires a comment"):
        await decide(db_session, batch, decision="approve", actor="approver", comment="")

    await decide(
        db_session,
        batch,
        decision="approve",
        actor="approver",
        comment="known intent regression, shipping anyway",
    )

    stored = await db_session.get(GovIngestBatch, batch.id)
    assert stored.stats_json["approval"]["override"] is True
    assert stored.stats_json["approval"]["threshold_failures"] == [
        "intent.pass_rate=0.500 is below 0.900"
    ]


async def test_auto_mode_never_overrides_soft_failures(
    db_session: AsyncSession,
) -> None:
    _, batch, _ = await _setup(
        db_session,
        approval_mode="auto",
        eval_status="failed",
        threshold_failures=["retrieval.pass_rate=0.500 is below 0.900"],
    )

    with pytest.raises(ApprovalBlockedError, match="manual mode"):
        await decide(db_session, batch, decision="approve", actor="worker", comment="ship it")


async def test_approver_needs_clearance_for_the_batch_maximum(
    db_session: AsyncSession,
) -> None:
    _, batch, document = await _setup(db_session, classification=4)

    with pytest.raises(ApprovalBlockedError, match="clearance"):
        await decide(
            db_session,
            batch,
            decision="approve",
            actor="approver",
            comment="ok",
            actor_clearance=2,
        )
    assert (await db_session.get(Document, document.id)).published is False

    await decide(
        db_session,
        batch,
        decision="approve",
        actor="approver",
        comment="ok",
        actor_clearance=4,
    )
    assert (await db_session.get(Document, document.id)).published is True


async def test_missing_evaluation_blocks_approval(db_session: AsyncSession) -> None:
    _, batch, _ = await _setup(db_session, with_eval=False)

    with pytest.raises(ApprovalBlockedError, match="no evaluation report"):
        await decide(db_session, batch, decision="approve", actor="approver", comment="ok")


async def test_unclassified_document_blocks_approval(
    db_session: AsyncSession,
) -> None:
    _, batch, _ = await _setup(db_session, classification=None)

    with pytest.raises(ApprovalBlockedError, match="no classification"):
        await decide(
            db_session,
            batch,
            decision="approve",
            actor="approver",
            comment="ok",
            actor_clearance=5,
        )


async def test_api_approval_publishes_and_lists_history(client, db_session: AsyncSession) -> None:
    _, batch, document = await _setup(db_session)

    response = await client.post(
        f"/api/v1/rag-governance/batches/{batch.id}/approval",
        json={"decision": "approve", "comment": "looks good"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["batch"]["status"] == "published"
    assert body["approval"]["decision"] == "approve"
    assert body["approval"]["actor_id"] == "governance-tester"

    history = await client.get(f"/api/v1/rag-governance/batches/{batch.id}/approvals")
    assert [item["decision"] for item in history.json()["items"]] == ["approve"]
    # The API committed through another session; drop this session's
    # cached copy before asserting the publication flag.
    await db_session.refresh(document)
    assert document.published is True


async def test_api_hard_gate_is_a_conflict(client, db_session: AsyncSession) -> None:
    _, batch, _ = await _setup(
        db_session,
        eval_status="failed",
        hard_gates=["case-0005/access-leak: fin-exec-compensation"],
    )

    response = await client.post(
        f"/api/v1/rag-governance/batches/{batch.id}/approval",
        json={"decision": "approve", "comment": "override"},
    )

    assert response.status_code == 409
    assert "hard gates failed" in response.json()["detail"]


async def test_api_rejection_without_comment_is_unprocessable(
    client, db_session: AsyncSession
) -> None:
    _, batch, _ = await _setup(db_session)

    response = await client.post(
        f"/api/v1/rag-governance/batches/{batch.id}/approval",
        json={"decision": "reject", "comment": ""},
    )

    assert response.status_code == 422


async def test_api_unknown_batch_is_404(client) -> None:
    response = await client.post(
        "/api/v1/rag-governance/batches/missing/approval",
        json={"decision": "approve", "comment": "ok"},
    )
    assert response.status_code == 404


async def test_approval_requires_authentication(raw_client) -> None:
    response = await raw_client.post(
        "/api/v1/rag-governance/batches/x/approval",
        json={"decision": "approve", "comment": "ok"},
    )
    assert response.status_code == 401
