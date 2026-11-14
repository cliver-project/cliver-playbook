"""Durable run events and the process-local wakeup bus.

The event log is the source of truth for clients: the worker persists every
event before anything else observes it, and streams replay or tail the log by
sequence. The broadcaster only wakes same-process tails so latency stays low;
correctness never depends on it.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentRunEvent


class EventStore:
    """Append-only event log for runs, read back in sequence order."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def persist(self, run_id: str, event: dict) -> int:
        """Store one event; returns the sequence it was written under."""
        sequence = event.get("sequence")
        if not isinstance(sequence, int):
            sequence = await self.next_sequence(run_id)
        payload = {**event, "run_id": run_id, "sequence": sequence}
        self.db.add(
            AgentRunEvent(
                run_id=run_id,
                sequence=sequence,
                event_type=str(payload["type"]),
                payload=payload,
            )
        )
        await self.db.commit()
        return sequence

    async def next_sequence(self, run_id: str) -> int:
        current = await self.db.scalar(
            select(func.max(AgentRunEvent.sequence)).where(AgentRunEvent.run_id == run_id)
        )
        return int(current if current is not None else -1) + 1

    async def after(self, run_id: str, after_sequence: int, limit: int = 200) -> list[dict]:
        """Every persisted event with ``sequence > after_sequence``, in order."""
        rows = await self.db.execute(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id, AgentRunEvent.sequence > after_sequence)
            .order_by(AgentRunEvent.sequence)
            .limit(limit)
        )
        return [row.payload for row in rows.scalars()]


class Broadcaster:
    """Wakes tailing streams in this process when a new event is persisted."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Event]] = {}

    def subscribe(self, run_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._subscribers.setdefault(run_id, []).append(event)
        return event

    def unsubscribe(self, run_id: str, event: asyncio.Event) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers is None:
            return
        try:
            subscribers.remove(event)
        except ValueError:
            pass
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def notify(self, run_id: str) -> None:
        for event in list(self._subscribers.get(run_id, [])):
            event.set()


broadcaster = Broadcaster()
