"""Run execution decoupled from HTTP requests.

``POST /agent/runs`` only persists a queued run and wakes the local queue.
A PostgreSQL-backed queue leases one run per worker with
``FOR UPDATE SKIP LOCKED``; every API process can run the queue safely.
The executor persists every event before publishing the wakeup, honours
cancellation while the model is quiet, and heartbeats so a crashed worker
can be detected. Streams never execute a run — they replay and tail the
event log, so reconnects and concurrent readers cannot repeat side effects.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

from app.agents.contracts import AgentContext
from app.agents.events import EventStore, broadcaster
from app.agents.proposals import build_proposal_generator
from app.agents.runs import DatabaseRunStore
from cliver_playbook.app.basic.db.session import open_session

if TYPE_CHECKING:
    from app.agents.coordinator import Coordinator

logger = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = frozenset({"run.completed", "run.failed"})
_HEARTBEAT_SECONDS = 2.0
_QUEUE_CAPACITY = 100


async def fail_run(
    store: DatabaseRunStore, events: EventStore, run_id: str, *, code: str, message: str
) -> None:
    """Persist a synthetic terminal failure event and mark the run failed."""
    sequence = await events.next_sequence(run_id)
    await events.persist(
        run_id,
        {"type": "run.failed", "sequence": sequence, "code": code, "message": message},
    )
    await store.set_status(run_id, "failed")
    broadcaster.notify(run_id)


async def execute_run(
    run_id: str,
    *,
    message: str,
    user_id: int | None,
    session_id: str | None,
    settings: Any,
    coordinator: Coordinator,
    already_claimed: bool = False,
) -> None:
    store_db = open_session()
    tool_db = open_session()
    learning_db = open_session()
    store = DatabaseRunStore(store_db)
    events = EventStore(store_db)
    context = AgentContext(
        run_id=run_id,
        message=message,
        user_id=user_id,
        session_id=session_id,
        resources={
            "db": tool_db,
            "learning_db": learning_db,
            "proposal_generator": build_proposal_generator(settings),
        },
    )
    try:
        if not already_claimed and not await store.claim(run_id):
            return  # cancelled while queued, or another worker claimed it

        queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_QUEUE_CAPACITY)
        failures: list[BaseException] = []

        async def pump() -> None:
            try:
                async for event in coordinator.stream(context):
                    await queue.put(event)
            except BaseException as exc:  # noqa: BLE001 — re-raised below
                failures.append(exc)
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        last_heartbeat = time.monotonic()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=settings.agent_run_tick_seconds
                    )
                except TimeoutError:
                    # The model or a tool is quiet; keep cancellation and the
                    # heartbeat responsive instead of blocking on the stream.
                    if await store.is_cancelled(run_id):
                        await _finish_cancelled(store, events, run_id)
                        return
                    if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
                        await store.touch(run_id)
                        last_heartbeat = time.monotonic()
                    continue
                if event is None:
                    break
                if await store.is_cancelled(run_id):
                    await _finish_cancelled(store, events, run_id)
                    return
                await events.persist(run_id, event)
                broadcaster.notify(run_id)
                last_heartbeat = time.monotonic()
                if event.get("type") in TERMINAL_EVENT_TYPES:
                    await store.set_status(
                        run_id, "completed" if event["type"] == "run.completed" else "failed"
                    )
                    return
            if failures:
                raise failures[0]
            await fail_run(
                store,
                events,
                run_id,
                code="incomplete",
                message="The run ended without a terminal event.",
            )
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    except asyncio.CancelledError:
        # Process shutdown or caller cancellation: best-effort terminal event.
        with contextlib.suppress(Exception):
            await store_db.rollback()
            await fail_run(
                store,
                events,
                run_id,
                code="interrupted",
                message="The API process stopped while the run was executing.",
            )
        raise
    except BaseException as exc:
        logger.exception("Agent run %s failed", run_id)
        with contextlib.suppress(Exception):
            await store_db.rollback()
            await fail_run(store, events, run_id, code="agent_error", message=str(exc))
    finally:
        with contextlib.suppress(Exception):
            await store_db.close()
        with contextlib.suppress(Exception):
            await tool_db.close()
        with contextlib.suppress(Exception):
            await learning_db.close()


async def _finish_cancelled(store: DatabaseRunStore, events: EventStore, run_id: str) -> None:
    sequence = await events.next_sequence(run_id)
    await events.persist(
        run_id,
        {
            "type": "run.failed",
            "sequence": sequence,
            "code": "cancelled",
            "message": "Run cancelled",
        },
    )
    await store.set_status(run_id, "cancelled")
    broadcaster.notify(run_id)
