"""Run state seam.

``DatabaseRunStore`` is the generated default: run state survives requests
and process restarts, and cancelling a queued run also writes the terminal
event so replay shows why nothing executed. ``InMemoryRunStore`` remains a
small ephemeral alternative; it keeps run state only, without the event log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import EventStore
from app.agents.models import AgentRun

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


@dataclass
class RunRecord:
    run_id: str
    message: str
    user_id: int | None = None
    session_id: str | None = None
    idempotency_key: str | None = None
    status: str = "queued"
    cancelled: bool = False


class RunStore(Protocol):
    """The run-state seam used by the routes and the run worker."""

    async def create(
        self,
        run_id: str,
        *,
        message: str,
        user_id: int | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord: ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def find_by_idempotency_key(
        self, key: str, *, user_id: int | None
    ) -> RunRecord | None: ...

    async def claim(self, run_id: str) -> bool: ...

    async def claim_next(self) -> RunRecord | None: ...

    async def cancel(self, run_id: str) -> RunRecord | None: ...

    async def is_cancelled(self, run_id: str) -> bool: ...

    async def set_status(self, run_id: str, status: str) -> None: ...

    async def touch(self, run_id: str) -> None: ...

    async def mark_orphaned_if_stale(self, run_id: str, stale_seconds: float) -> bool: ...


class InMemoryRunStore:
    """Explicit ephemeral store; run state only, no event log."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    async def create(
        self,
        run_id: str,
        *,
        message: str,
        user_id: int | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        if run_id in self._runs:
            raise ValueError(f"Run {run_id!r} already exists")
        if (
            idempotency_key is not None
            and await self.find_by_idempotency_key(idempotency_key, user_id=user_id) is not None
        ):
            raise ValueError(f"Idempotency key {idempotency_key!r} is already used")
        record = RunRecord(
            run_id=run_id,
            message=message,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        self._runs[run_id] = record
        return record

    async def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def find_by_idempotency_key(self, key: str, *, user_id: int | None) -> RunRecord | None:
        for record in self._runs.values():
            if record.idempotency_key == key and record.user_id == user_id:
                return record
        return None

    async def claim(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        if record is None or record.status != "queued":
            return False
        record.status = "running"
        return True

    async def claim_next(self) -> RunRecord | None:
        for record in self._runs.values():
            if record.status == "queued":
                record.status = "running"
                return record
        return None

    async def cancel(self, run_id: str) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None or record.status in TERMINAL_STATUSES:
            return record
        record.cancelled = True
        if record.status == "queued":
            record.status = "cancelled"
        return record

    async def is_cancelled(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        return bool(record and record.cancelled)

    async def set_status(self, run_id: str, status: str) -> None:
        record = self._runs.get(run_id)
        if record is not None:
            record.status = status

    async def touch(self, run_id: str) -> None:
        return None

    async def mark_orphaned_if_stale(self, run_id: str, stale_seconds: float) -> bool:
        return False


class DatabaseRunStore:
    """PostgreSQL-backed run store using one async session."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        run_id: str,
        *,
        message: str,
        user_id: int | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        if await self._row(run_id) is not None:
            raise ValueError(f"Run {run_id!r} already exists")
        row = AgentRun(
            run_id=run_id,
            message=message,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        self.db.add(row)
        await self.db.commit()
        return _record(row)

    async def get(self, run_id: str) -> RunRecord | None:
        row = await self._row(run_id)
        return _record(row) if row is not None else None

    async def find_by_idempotency_key(self, key: str, *, user_id: int | None) -> RunRecord | None:
        owner = AgentRun.user_id.is_(None) if user_id is None else AgentRun.user_id == user_id
        row = (
            await self.db.execute(
                select(AgentRun).where(
                    AgentRun.idempotency_key == key,
                    owner,
                )
            )
        ).scalar_one_or_none()
        return _record(row) if row is not None else None

    async def claim(self, run_id: str) -> bool:
        """Atomically move a queued run to running; exactly one caller wins."""
        result = await self.db.execute(
            update(AgentRun)
            .where(AgentRun.run_id == run_id, AgentRun.status == "queued")
            .values(status="running")
        )
        await self.db.commit()
        return bool(result.rowcount)

    async def claim_next(self) -> RunRecord | None:
        """Atomically lease the oldest queued run; SKIP LOCKED allows workers."""
        row = await self.db.scalar(
            select(AgentRun)
            .where(AgentRun.status == "queued")
            .order_by(AgentRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        row.status = "running"
        row.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(row)
        return _record(row)

    async def cancel(self, run_id: str) -> RunRecord | None:
        row = await self._row(run_id)
        if row is None:
            return None
        if row.status in TERMINAL_STATUSES:
            return _record(row)
        if row.status == "queued":
            # Won the race with the worker: nothing executed, so this side
            # writes the terminal event itself and replay shows why.
            result = await self.db.execute(
                update(AgentRun)
                .where(AgentRun.run_id == run_id, AgentRun.status == "queued")
                .values(status="cancelled", cancelled=True)
            )
            if result.rowcount:
                await EventStore(self.db).persist(
                    run_id,
                    {"type": "run.failed", "code": "cancelled", "message": "Run cancelled"},
                )
                return _record(await self._row(run_id))
            row = await self._row(run_id)
            if row is None or row.status in TERMINAL_STATUSES:
                return _record(row)
        # The worker owns the run now: set the flag, it emits the event.
        await self.db.execute(
            update(AgentRun)
            .where(AgentRun.run_id == run_id, AgentRun.status == "running")
            .values(cancelled=True)
        )
        await self.db.commit()
        return _record(await self._row(run_id))

    async def is_cancelled(self, run_id: str) -> bool:
        row = await self._row(run_id)
        return bool(row and row.cancelled)

    async def set_status(self, run_id: str, status: str) -> None:
        row = await self._row(run_id)
        if row is None:
            return
        row.status = status
        await self.db.commit()

    async def touch(self, run_id: str) -> None:
        """Heartbeat: prove this worker is still alive for orphan detection."""
        await self.db.execute(
            update(AgentRun).where(AgentRun.run_id == run_id).values(updated_at=func.now())
        )
        await self.db.commit()

    async def mark_orphaned_if_stale(self, run_id: str, stale_seconds: float) -> bool:
        """Fail a running run whose worker stopped heartbeating.

        Queued runs are left for a live queue consumer; a backlog is not an
        orphan. A deployment with no worker should surface that separately.
        """
        result = await self.db.execute(
            update(AgentRun)
            .where(
                AgentRun.run_id == run_id,
                AgentRun.status == "running",
                AgentRun.updated_at < func.now() - timedelta(seconds=stale_seconds),
            )
            .values(status="failed")
        )
        await self.db.commit()
        return bool(result.rowcount)

    async def _row(self, run_id: str) -> AgentRun | None:
        """Read through the identity map so another session's writes are seen."""
        result = await self.db.execute(
            select(AgentRun)
            .where(AgentRun.run_id == run_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()


def _record(row: AgentRun) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        message=row.message,
        user_id=row.user_id,
        session_id=row.session_id,
        idempotency_key=row.idempotency_key,
        status=row.status,
        cancelled=row.cancelled,
    )
