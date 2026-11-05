"""Durable queue behaviour: idempotent enqueue, exclusive claim, retry.

The retry test relies on the test settings' zero backoff: production
delays a retry exponentially, but the state machine must be provable
without sleeping.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.rag_governance.models import GovJob
from cliver_playbook.app.rag_governance.runtime import (
    claim_next,
    complete,
    enqueue,
    fail,
    run_worker,
)


async def test_enqueue_is_idempotent_by_dedupe_key(db_session: AsyncSession) -> None:
    a = await enqueue(
        db_session, project_id="p", kind="ingest_batch", payload={"n": 1}, dedupe_key="k"
    )
    b = await enqueue(
        db_session, project_id="p", kind="ingest_batch", payload={"n": 2}, dedupe_key="k"
    )
    assert a.id == b.id
    assert b.payload_json == {"n": 1}


async def test_claim_only_returns_queued_jobs(db_session: AsyncSession) -> None:
    job = await enqueue(db_session, project_id="p", kind="run_eval", payload={})

    claimed = await claim_next(db_session, "worker-1")

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.worker_id == "worker-1"
    assert await claim_next(db_session, "worker-2") is None


async def test_claim_skips_a_job_that_is_backing_off(db_session: AsyncSession) -> None:
    job = await enqueue(db_session, project_id="p", kind="run_eval", payload={})
    job.available_at = datetime.now(UTC) + timedelta(seconds=60)
    await db_session.commit()

    assert await claim_next(db_session, "worker") is None


async def test_failure_retries_then_marks_failed(db_session: AsyncSession) -> None:
    job = await enqueue(db_session, project_id="p", kind="run_eval", payload={})

    for _ in range(3):
        claimed = await claim_next(db_session, "worker")
        assert claimed is not None
        await fail(db_session, claimed, "boom")

    final = await db_session.get(GovJob, job.id)
    assert final is not None
    assert final.status == "failed"
    assert final.attempts == 3
    assert final.error == "boom"


async def test_complete_marks_the_job_succeeded(db_session: AsyncSession) -> None:
    job = await enqueue(db_session, project_id="p", kind="run_eval", payload={})
    claimed = await claim_next(db_session, "worker")
    assert claimed is not None

    await complete(db_session, claimed, {"rows": 2})

    final = await db_session.get(GovJob, job.id)
    assert final is not None
    assert final.status == "succeeded"
    assert final.result_json == {"rows": 2}
    assert final.finished_at is not None


async def test_worker_dispatches_until_stopped(db_session: AsyncSession) -> None:
    job = await enqueue(db_session, project_id="p", kind="run_eval", payload={})
    # The worker opens its own session, which cannot see this
    # transaction's uncommitted row.
    await db_session.commit()

    stop = asyncio.Event()
    seen: list[str] = []

    async def handler(db: AsyncSession, claimed: GovJob) -> dict:
        seen.append(claimed.id)
        stop.set()
        return {"ok": True}

    await asyncio.wait_for(
        run_worker(
            stop,
            {"run_eval": handler},
            poll_seconds=0.01,
            session_factory=runtime.session_factory(),
        ),
        timeout=5,
    )

    assert seen == [job.id]
    async with runtime.session_factory()() as check:
        final = await check.get(GovJob, job.id)
        assert final is not None
        assert final.status == "succeeded"
        assert final.result_json == {"ok": True}
