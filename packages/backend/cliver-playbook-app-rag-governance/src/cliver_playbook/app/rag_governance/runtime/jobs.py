"""Durable job queue: enqueue, claim, finish, retry.

A ``gov_jobs`` row is the unit of work, so a process restart loses no
queued work and two workers cannot run the same job. The claim is a
single transaction: select the oldest eligible queued row with
``FOR UPDATE SKIP LOCKED`` (Postgres) and mark it running. SQLite has
no row locks, so the claim degrades to a plain select — fine for the
single-worker test suite, and the production database is Postgres.

Retry is bounded and backed off. ``attempts`` counts *failed* runs, so
a job that raises on its first claim is retried until
``job_max_attempts`` is reached; the backoff doubles per attempt and is
configurable to zero for deterministic tests.

``enqueue`` is idempotent on ``dedupe_key``: a caller may retry an API
request or a scheduler may fire twice, and the second enqueue returns
the existing row instead of duplicating the work. The unique index is
the final guard; the pre-check avoids the common case's exception.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.models.entities import GovJob
from cliver_playbook.app.rag_governance.settings import settings

logger = logging.getLogger("cliver_playbook.app.rag_governance.runtime.jobs")


async def enqueue(
    db: AsyncSession,
    *,
    project_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> GovJob:
    """Insert a queued job, or return the existing row for ``dedupe_key``."""
    if dedupe_key is not None:
        existing = await db.scalar(select(GovJob).where(GovJob.dedupe_key == dedupe_key))
        if existing is not None:
            return existing

    job = GovJob(
        project_id=project_id,
        kind=kind,
        payload_json=payload or {},
        dedupe_key=dedupe_key,
        status="queued",
        attempts=0,
    )
    try:
        # A savepoint keeps a lost race from discarding the caller's
        # earlier work in the same transaction.
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
        if dedupe_key is None:
            raise
        existing = await db.scalar(select(GovJob).where(GovJob.dedupe_key == dedupe_key))
        if existing is None:
            raise
        return existing
    return job


async def claim_next(db: AsyncSession, worker_id: str) -> GovJob | None:
    """Claim the oldest eligible queued job, or return None.

    The row is marked running in the same transaction as the select, so
    no other worker can claim it. ``available_at`` gates retry backoff;
    a NULL value means immediately eligible.
    """
    now = datetime.now(UTC)
    statement = (
        select(GovJob)
        .where(
            GovJob.status == "queued",
            or_(GovJob.available_at.is_(None), GovJob.available_at <= now),
        )
        .order_by(GovJob.created_at, GovJob.id)
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    job = await db.scalar(statement)
    if job is None:
        return None

    job.status = "running"
    job.worker_id = worker_id
    job.started_at = now
    await db.commit()
    return job


async def complete(db: AsyncSession, job: GovJob, result: dict[str, Any] | None) -> None:
    """Mark a claimed job succeeded and persist its result."""
    job.status = "succeeded"
    job.result_json = result or {}
    job.error = None
    job.finished_at = datetime.now(UTC)
    job.worker_id = None
    await db.commit()


async def fail(db: AsyncSession, job: GovJob, error: str) -> None:
    """Record a failure; retry with backoff or mark the job failed."""
    now = datetime.now(UTC)
    job.attempts = (job.attempts or 0) + 1
    job.error = error
    job.worker_id = None

    if job.attempts >= settings.rag_governance.job_max_attempts:
        job.status = "failed"
        job.finished_at = now
    else:
        base = settings.rag_governance.job_retry_backoff_seconds
        job.status = "queued"
        job.finished_at = None
        job.available_at = now + timedelta(seconds=base * (2 ** (job.attempts - 1)))
    await db.commit()


async def run_worker(
    stop: Any,
    handlers: dict[str, Any],
    *,
    poll_seconds: float = 1.0,
    session_factory: Any = None,
) -> None:
    """Poll and dispatch until ``stop`` is set.

    ``handlers`` maps a job kind to ``async (db, job) -> dict | None``.
    An unregistered kind fails the job instead of silently dropping it.
    The session factory defaults to the process runtime; tests pass
    their own so the worker can run on a fixture's engine.
    """
    if session_factory is None:
        from cliver_playbook.app.basic import runtime

        session_factory = runtime.session_factory()

    worker_id = f"worker-{uuid4()}"
    while not stop.is_set():
        job = None
        async with session_factory() as db:
            job = await claim_next(db, worker_id)
            if job is not None:
                handler = handlers.get(job.kind)
                try:
                    if handler is None:
                        raise LookupError(f"no handler registered for job kind {job.kind!r}")
                    result = await handler(db, job)
                except Exception as exc:
                    # A handler failure is data, not a crash: record it on the job.
                    logger.exception("governance job failed (id=%s kind=%s)", job.id, job.kind)
                    await fail(db, job, str(exc))
                else:
                    await complete(db, job, result)

        # Sleep only when nothing was claimed, so a busy queue drains
        # without a poll delay. The stop check happens next iteration.
        if job is None:
            await asyncio.sleep(poll_seconds)
