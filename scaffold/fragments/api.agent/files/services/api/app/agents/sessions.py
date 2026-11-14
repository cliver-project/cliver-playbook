"""Conversation history derived from the durable run and event tables.

A session is a group of runs sharing ``session_id`` for one owner. The
grouping query is user-scoped: an authenticated caller only sees their own
runs, and an auth-disabled deployment only sees runs created without a user.
Events are returned in replay order and capped per run so a long tool loop
cannot turn a history request into an unbounded payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentRun, AgentRunEvent

MAX_EVENTS_PER_RUN = 200


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    last_message: str
    run_count: int
    updated_at: datetime


@dataclass(frozen=True)
class SessionRun:
    run_id: str
    message: str
    status: str
    created_at: datetime
    events: list[dict]


def _owned(user_id: int | None):
    if user_id is None:
        return AgentRun.user_id.is_(None)
    return AgentRun.user_id == user_id


async def list_sessions(
    db: AsyncSession, *, user_id: int | None, limit: int = 50
) -> list[SessionSummary]:
    """Return the owner's sessions, newest first."""
    latest = (
        select(
            AgentRun.session_id.label("session_id"),
            AgentRun.message.label("last_message"),
            func.row_number()
            .over(
                partition_by=AgentRun.session_id,
                order_by=(AgentRun.created_at.desc(), AgentRun.run_id.desc()),
            )
            .label("position"),
        )
        .where(AgentRun.session_id.is_not(None), _owned(user_id))
        .subquery()
    )
    totals = (
        select(
            AgentRun.session_id.label("session_id"),
            func.count().label("run_count"),
            func.max(AgentRun.updated_at).label("updated_at"),
        )
        .where(AgentRun.session_id.is_not(None), _owned(user_id))
        .group_by(AgentRun.session_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                latest.c.session_id,
                latest.c.last_message,
                totals.c.run_count,
                totals.c.updated_at,
            )
            .join(totals, latest.c.session_id == totals.c.session_id)
            .where(latest.c.position == 1)
            .order_by(totals.c.updated_at.desc(), totals.c.session_id)
            .limit(limit)
        )
    ).all()
    return [
        SessionSummary(
            session_id=str(row.session_id),
            last_message=str(row.last_message),
            run_count=int(row.run_count),
            updated_at=row.updated_at,
        )
        for row in rows
    ]


async def get_session_runs(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: int | None,
    limit: int = 20,
) -> list[SessionRun] | None:
    """Return the newest ``limit`` runs oldest-first, or ``None`` if absent."""
    rows = list(
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.session_id == session_id, _owned(user_id))
                .order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    rows.reverse()
    runs: list[SessionRun] = []
    for row in rows:
        payloads = list(
            (
                await db.execute(
                    select(AgentRunEvent.payload)
                    .where(AgentRunEvent.run_id == row.run_id)
                    .order_by(AgentRunEvent.sequence.desc())
                    .limit(MAX_EVENTS_PER_RUN)
                )
            )
            .scalars()
            .all()
        )
        payloads.reverse()
        runs.append(
            SessionRun(
                run_id=row.run_id,
                message=row.message,
                status=row.status,
                created_at=row.created_at,
                events=[dict(payload) for payload in payloads],
            )
        )
    return runs
