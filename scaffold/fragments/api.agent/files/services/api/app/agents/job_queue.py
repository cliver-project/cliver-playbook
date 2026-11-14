"""PostgreSQL-backed run queue worker.

The queue uses ``FOR UPDATE SKIP LOCKED`` to lease queued runs, so every API
process (or a dedicated worker process) can run the same loop safely. The
queue is intentionally in-process per app; adding more processes adds
consumers, not duplicate execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.agents.factory import build_coordinator
from app.agents.runs import DatabaseRunStore, RunRecord
from app.agents.worker import execute_run
from app.settings import Settings
from cliver_playbook.app.basic.db.session import open_session

logger = logging.getLogger(__name__)

_wake = asyncio.Event()
_loop_task: asyncio.Task[None] | None = None
_active: set[asyncio.Task[None]] = set()


async def start_job_queue(settings: Settings) -> None:
    """Start one queue consumer for this process, unless disabled."""
    global _loop_task
    if not settings.agent_run_worker_enabled:
        return
    if _loop_task is not None and not _loop_task.done():
        return
    _loop_task = asyncio.create_task(_run_loop(settings), name="agent-run-queue")
    _loop_task.add_done_callback(_log_loop_failure)


async def stop_job_queue() -> None:
    """Stop polling and cancel in-flight runs (they persist interrupted)."""
    global _loop_task
    loop_task, _loop_task = _loop_task, None
    if loop_task is not None:
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
    active = list(_active)
    _active.clear()
    for task in active:
        task.cancel()
    if active:
        await asyncio.gather(*active, return_exceptions=True)


def wake_job_queue() -> None:
    """Nudge the local consumer so a fresh run does not wait for the poll."""
    _wake.set()


async def _run_loop(settings: Settings) -> None:
    while True:
        for task in list(_active):
            if task.done():
                _active.discard(task)
        while len(_active) < settings.agent_run_concurrency:
            try:
                record = await _claim_next()
            except Exception:  # a transient DB error must not kill the queue
                logger.exception("Run queue claim failed")
                break
            if record is None:
                break
            task = asyncio.create_task(
                _consume(settings, record),
                name=f"agent-run-{record.run_id}",
            )
            _active.add(task)
            task.add_done_callback(_active.discard)

        try:
            await asyncio.wait_for(_wake.wait(), timeout=settings.agent_job_poll_seconds)
        except TimeoutError:
            pass
        finally:
            _wake.clear()


async def _claim_next() -> RunRecord | None:
    db = open_session()
    try:
        return await DatabaseRunStore(db).claim_next()
    finally:
        await db.close()


async def _consume(settings: Settings, record: RunRecord) -> None:
    coordinator = build_coordinator(settings)
    await execute_run(
        record.run_id,
        message=record.message,
        user_id=record.user_id,
        session_id=record.session_id,
        settings=settings,
        coordinator=coordinator,
        already_claimed=True,
    )


def _log_loop_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Run queue loop stopped", exc_info=exc)
