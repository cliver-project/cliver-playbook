"""Project lifecycle: create, read, update; config is versioned.

A project is the unit the whole loop hangs off: one collection, one
approval mode, one active configuration. The configuration is not
mutated in place: every accepted change appends a ``gov_config_versions``
row and points ``active_config_version`` at it, so an evaluation report
can always name the configuration that produced its corpus.

Unknown configuration keys are rejected. A typo such as ``threshold``
instead of ``thresholds`` would otherwise sit in JSONB forever while
every consumer silently used its default — the exact failure the
versioning is supposed to make auditable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.models.entities import GovConfigVersion, GovProject

APPROVAL_MODES: frozenset[str] = frozenset({"manual", "auto", "hybrid"})

# The configuration surface the loop defines (R8). Intent rules and
# golden sets are referenced by id and version, never copied here.
PROJECT_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "taxonomy",
        "type_policies",
        "masking",
        "embedding",
        "chunking",
        "retrieval",
        "evaluation",
        "thresholds",
        "scope_combination",
        "tools",
        "freshness",
        "golden",
    }
)


class ProjectValidationError(ValueError):
    """The request is wrong: an unknown mode, config key, or slug."""


class ProjectSlugTakenError(ValueError):
    """The slug already names another project."""


def validate_config(config: dict[str, Any]) -> None:
    """Reject unknown or non-object configuration."""
    if not isinstance(config, dict):
        raise ProjectValidationError("config must be a JSON object")
    unknown = sorted(set(config) - PROJECT_CONFIG_KEYS)
    if unknown:
        raise ProjectValidationError("unknown config key(s): " + ", ".join(unknown))


async def create_project(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    approval_mode: str = "manual",
    description: str = "",
    collection_id: str | None = None,
    config: dict[str, Any] | None = None,
    actor: str = "",
) -> GovProject:
    """Create a draft project and its first active config version."""
    if approval_mode not in APPROVAL_MODES:
        raise ProjectValidationError(f"approval_mode must be one of {sorted(APPROVAL_MODES)}")
    resolved_config = config or {}
    validate_config(resolved_config)

    exists = await db.scalar(select(GovProject.id).where(GovProject.slug == slug))
    if exists is not None:
        raise ProjectSlugTakenError(f"project slug {slug!r} is already in use")

    project = GovProject(
        slug=slug,
        name=name,
        description=description,
        approval_mode=approval_mode,
        collection_id=collection_id or slug,
        config_json=resolved_config,
        created_by=actor,
    )
    db.add(project)
    try:
        await db.flush()
        db.add(
            GovConfigVersion(
                project_id=project.id,
                version=1,
                config_json=resolved_config,
                status="active",
                created_by=actor,
            )
        )
        project.active_config_version = 1
        await db.commit()
        # ``created_at``/``updated_at`` are server defaults; the INSERT
        # did not return them, so load the row before the response
        # serializer touches an expired attribute outside the greenlet.
        await db.refresh(project)
    except IntegrityError:
        # The pre-check loses a race with a concurrent create; the
        # unique slug index is the real guard.
        await db.rollback()
        raise ProjectSlugTakenError(f"project slug {slug!r} is already in use") from None
    return project


async def list_projects(db: AsyncSession) -> list[GovProject]:
    rows = await db.execute(select(GovProject).order_by(GovProject.created_at.desc()))
    return list(rows.scalars().all())


async def get_project(db: AsyncSession, project_id: str) -> GovProject | None:
    return await db.get(GovProject, project_id)


async def update_project(
    db: AsyncSession,
    project: GovProject,
    *,
    name: str | None = None,
    description: str | None = None,
    approval_mode: str | None = None,
    config: dict[str, Any] | None = None,
    actor: str = "",
) -> GovProject:
    """Apply the provided fields; a changed config becomes a new version."""
    if approval_mode is not None:
        if approval_mode not in APPROVAL_MODES:
            raise ProjectValidationError(f"approval_mode must be one of {sorted(APPROVAL_MODES)}")
        project.approval_mode = approval_mode
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description

    if config is not None and config != project.config_json:
        validate_config(config)
        next_version = (
            await db.scalar(
                select(func.max(GovConfigVersion.version)).where(
                    GovConfigVersion.project_id == project.id
                )
            )
            or 0
        ) + 1
        db.add(
            GovConfigVersion(
                project_id=project.id,
                version=next_version,
                config_json=config,
                status="active",
                created_by=actor,
            )
        )
        project.config_json = config
        project.active_config_version = next_version

    await db.commit()
    await db.refresh(project)
    return project
