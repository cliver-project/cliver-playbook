"""Versioned golden sets, prompt history and per-agent learning summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    AgentConfig,
    AgentConfigVersion,
    AgentEvaluation,
    AgentExperience,
    AgentFeedback,
    AgentGoldenCase,
    AgentGoldenSetVersion,
    AgentImprovement,
)


class VersionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class GoldenCaseSnapshot:
    id: int
    name: str
    message: str
    expected_contains: list[str] = field(default_factory=list)
    forbidden_contains: list[str] = field(default_factory=list)


async def publish_golden_set(
    db: AsyncSession,
    agent: str,
    *,
    actor_id: int | None,
    note: str = "",
) -> AgentGoldenSetVersion:
    cases = list(
        (
            await db.scalars(
                select(AgentGoldenCase)
                .where(
                    AgentGoldenCase.agent == agent,
                    AgentGoldenCase.enabled.is_(True),
                )
                .order_by(AgentGoldenCase.id)
            )
        ).all()
    )
    if not cases:
        raise VersionError("No enabled golden cases to publish", 422)

    max_version = (
        await db.scalar(
            select(func.max(AgentGoldenSetVersion.version)).where(
                AgentGoldenSetVersion.agent == agent
            )
        )
        or 0
    )
    await db.execute(
        update(AgentGoldenSetVersion)
        .where(
            AgentGoldenSetVersion.agent == agent,
            AgentGoldenSetVersion.is_active.is_(True),
        )
        .values(is_active=False)
    )
    version = AgentGoldenSetVersion(
        agent=agent,
        version=max_version + 1,
        cases=[
            {
                "id": case.id,
                "name": case.name,
                "message": case.message,
                "expected_contains": case.expected_contains,
                "forbidden_contains": case.forbidden_contains,
            }
            for case in cases
        ],
        note=note.strip(),
        created_by=actor_id,
        is_active=True,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return version


async def list_golden_versions(db: AsyncSession, agent: str) -> list[AgentGoldenSetVersion]:
    return list(
        (
            await db.scalars(
                select(AgentGoldenSetVersion)
                .where(AgentGoldenSetVersion.agent == agent)
                .order_by(AgentGoldenSetVersion.version.desc())
            )
        ).all()
    )


async def active_golden_cases(db: AsyncSession, agent: str) -> list[GoldenCaseSnapshot] | None:
    version = await db.scalar(
        select(AgentGoldenSetVersion).where(
            AgentGoldenSetVersion.agent == agent,
            AgentGoldenSetVersion.is_active.is_(True),
        )
    )
    if version is None:
        return None
    snapshots: list[GoldenCaseSnapshot] = []
    for item in version.cases or []:
        snapshots.append(
            GoldenCaseSnapshot(
                id=int(item.get("id", 0)),
                name=str(item.get("name", "")),
                message=str(item.get("message", "")),
                expected_contains=[str(value) for value in (item.get("expected_contains") or [])],
                forbidden_contains=[str(value) for value in (item.get("forbidden_contains") or [])],
            )
        )
    return snapshots


async def activate_golden_version(db: AsyncSession, version_id: int) -> AgentGoldenSetVersion:
    version = await db.scalar(
        select(AgentGoldenSetVersion).where(AgentGoldenSetVersion.id == version_id)
    )
    if version is None:
        raise VersionError("Golden-set version not found", 404)
    await db.execute(
        update(AgentGoldenSetVersion)
        .where(AgentGoldenSetVersion.agent == version.agent)
        .values(is_active=False)
    )
    version.is_active = True
    await db.commit()
    await db.refresh(version)
    return version


async def list_config_versions(db: AsyncSession, agent: str) -> list[AgentConfigVersion]:
    return list(
        (
            await db.scalars(
                select(AgentConfigVersion)
                .where(AgentConfigVersion.agent == agent)
                .order_by(AgentConfigVersion.version.desc())
            )
        ).all()
    )


async def rollback_config(
    db: AsyncSession,
    agent: str,
    version_number: int,
    *,
    actor_id: int | None,
    note: str = "",
) -> AgentConfig:
    source = await db.scalar(
        select(AgentConfigVersion).where(
            AgentConfigVersion.agent == agent,
            AgentConfigVersion.version == version_number,
        )
    )
    if source is None:
        raise VersionError("Config version not found", 404)
    config = await db.scalar(
        select(AgentConfig).where(AgentConfig.agent == agent).with_for_update()
    )
    if config is None:
        raise VersionError("Agent config not found", 404)
    config.prompt_overlay = source.prompt_overlay
    config.rollout_percent = source.rollout_percent
    config.version += 1
    db.add(
        AgentConfigVersion(
            agent=agent,
            version=config.version,
            prompt_overlay=config.prompt_overlay,
            rollout_percent=config.rollout_percent,
            source_proposal_id=None,
            note=(note.strip() or f"Rollback to version {version_number}"),
            created_by=actor_id,
        )
    )
    await db.commit()
    await db.refresh(config)
    return config


async def agent_learning_summary(db: AsyncSession, agent: str) -> dict:
    config = await db.scalar(select(AgentConfig).where(AgentConfig.agent == agent))
    config_versions = (
        await db.scalar(
            select(func.count(AgentConfigVersion.id)).where(AgentConfigVersion.agent == agent)
        )
        or 0
    )
    active_golden = await db.scalar(
        select(AgentGoldenSetVersion).where(
            AgentGoldenSetVersion.agent == agent,
            AgentGoldenSetVersion.is_active.is_(True),
        )
    )
    proposal_counts: dict[str, int] = {}
    for status in ("pending", "approved", "applied", "rejected"):
        proposal_counts[status] = (
            await db.scalar(
                select(func.count(AgentImprovement.id)).where(
                    AgentImprovement.agent == agent,
                    AgentImprovement.status == status,
                )
            )
            or 0
        )
    feedback_count = (
        await db.scalar(
            select(func.count(AgentFeedback.id))
            .join(AgentExperience, AgentFeedback.experience_id == AgentExperience.id)
            .where(AgentExperience.agent == agent)
        )
        or 0
    )
    positive_feedback = (
        await db.scalar(
            select(func.count(AgentFeedback.id))
            .join(AgentExperience, AgentFeedback.experience_id == AgentExperience.id)
            .where(
                AgentExperience.agent == agent,
                AgentFeedback.rating >= 4,
            )
        )
        or 0
    )
    recent = list(
        (
            await db.scalars(
                select(AgentEvaluation)
                .join(
                    AgentExperience,
                    AgentEvaluation.experience_id == AgentExperience.id,
                )
                .where(AgentExperience.agent == agent)
                .order_by(AgentEvaluation.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    pass_rate = (
        round(sum(1 for evaluation in recent if evaluation.passed) / len(recent), 4)
        if recent
        else None
    )
    golden_versions = (
        await db.scalar(
            select(func.count(AgentGoldenSetVersion.id)).where(AgentGoldenSetVersion.agent == agent)
        )
        or 0
    )
    return {
        "agent": agent,
        "config_version": config.version if config is not None else None,
        "config_versions": config_versions,
        "prompt_overlay": config.prompt_overlay if config is not None else "",
        "rollout_percent": config.rollout_percent if config is not None else 100,
        "active_golden_version": active_golden.version if active_golden else None,
        "golden_versions": golden_versions,
        "proposal_counts": proposal_counts,
        "feedback_count": feedback_count,
        "positive_feedback": positive_feedback,
        "recent_pass_rate": pass_rate,
        "recent_evaluations": len(recent),
        "generated_at": datetime.now(UTC),
    }


async def set_rollout_percent(
    db: AsyncSession,
    agent: str,
    percent: int,
    *,
    actor_id: int | None,
    note: str = "",
) -> AgentConfig:
    """Set the staged rollout percentage and record it in config history."""
    if not 0 <= int(percent) <= 100:
        raise VersionError("rollout percent must be between 0 and 100", 422)
    config = await db.scalar(
        select(AgentConfig).where(AgentConfig.agent == agent).with_for_update()
    )
    if config is None:
        config = AgentConfig(
            agent=agent,
            prompt_overlay="",
            version=1,
            rollout_percent=int(percent),
        )
        db.add(config)
    else:
        config.rollout_percent = int(percent)
        config.version += 1
    db.add(
        AgentConfigVersion(
            agent=agent,
            version=config.version,
            prompt_overlay=config.prompt_overlay,
            rollout_percent=config.rollout_percent,
            source_proposal_id=None,
            note=(note.strip() or f"Rollout set to {percent}%"),
            created_by=actor_id,
        )
    )
    await db.commit()
    await db.refresh(config)
    return config
