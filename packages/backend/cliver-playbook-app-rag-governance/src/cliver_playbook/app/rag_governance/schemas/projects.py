"""Wire models for the project endpoints.

Responses are built with an explicit ``from_row`` instead of
``from_attributes`` because the ORM column is ``config_json`` while the
wire field is ``config``; an alias would make the mapping depend on a
Pydantic lookup rule that is easy to break silently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cliver_playbook.app.rag_governance.models.entities import GovProject

ApprovalMode = Literal["manual", "auto", "hybrid"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="Stable external identifier, lower-case kebab-case.",
    )
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4000)
    approval_mode: ApprovalMode = "manual"
    collection_id: str | None = Field(default=None, min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    approval_mode: ApprovalMode | None = None
    config: dict[str, Any] | None = None


class ProjectRead(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    status: str
    approval_mode: str
    collection_id: str
    config: dict[str, Any]
    active_config_version: int | None
    created_by: str
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, project: GovProject) -> ProjectRead:
        return cls(
            id=project.id,
            slug=project.slug,
            name=project.name,
            description=project.description,
            status=project.status,
            approval_mode=project.approval_mode,
            collection_id=project.collection_id,
            config=project.config_json,
            active_config_version=project.active_config_version,
            created_by=project.created_by,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectList(BaseModel):
    items: list[ProjectRead]
