"""The governance package's runtime settings section (ADR-0021).

Only process-wide knobs live here. Anything that describes a project
(approval mode, chunking policy, classification defaults, tool
bindings) belongs to the project's own row and config version, because
changing it must not silently rebuild every other project's behaviour.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cliver_playbook.app.basic.runtime_settings import (
    SettingsField,
    SettingsSection,
    SettingsValidationError,
    register_settings_section,
)

SECTION_KEY = "rag_governance"

_APPROVAL_MODES = ("manual", "auto", "hybrid")


class _GovernanceRuntimeSettings(BaseModel):
    worker_enabled: bool
    worker_poll_seconds: float = Field(gt=0)
    job_max_attempts: int = Field(ge=1)
    default_approval_mode: str
    mock_kingdee_url: str
    max_tool_rows: int = Field(ge=1)


def _fields() -> tuple[SettingsField, ...]:
    return (
        SettingsField(
            name="worker_enabled",
            label="Run the background worker",
            type="boolean",
            description="Ingestion, evaluation and sync jobs run only when the worker is enabled.",
            env_var="CLIVER_RAG_GOVERNANCE__WORKER_ENABLED",
        ),
        SettingsField(
            name="worker_poll_seconds",
            label="Worker poll interval (seconds)",
            type="number",
            minimum=0.1,
            description="How often the worker claims the next queued job.",
            env_var="CLIVER_RAG_GOVERNANCE__WORKER_POLL_SECONDS",
        ),
        SettingsField(
            name="job_max_attempts",
            label="Job attempts",
            type="integer",
            minimum=1,
            description="Failures before a job is marked failed instead of retried.",
            env_var="CLIVER_RAG_GOVERNANCE__JOB_MAX_ATTEMPTS",
        ),
        SettingsField(
            name="default_approval_mode",
            label="Default approval mode",
            type="enum",
            enum=_APPROVAL_MODES,
            description="Used only when a new project does not choose its own mode.",
            env_var="CLIVER_RAG_GOVERNANCE__DEFAULT_APPROVAL_MODE",
        ),
        SettingsField(
            name="mock_kingdee_url",
            label="Mock Kingdee endpoint",
            type="string",
            description="Optional base URL of the local mock ERP server; empty disables it.",
            env_var="CLIVER_RAG_GOVERNANCE__MOCK_KINGDEE_URL",
        ),
        SettingsField(
            name="max_tool_rows",
            label="Tool result row cap",
            type="integer",
            minimum=1,
            description="Upper bound on rows a governed tool may return per call.",
            env_var="CLIVER_RAG_GOVERNANCE__MAX_TOOL_ROWS",
        ),
    )


def _read(settings: Any) -> dict[str, Any]:
    block = settings.rag_governance
    return {
        "worker_enabled": block.worker_enabled,
        "worker_poll_seconds": block.worker_poll_seconds,
        "job_max_attempts": block.job_max_attempts,
        "default_approval_mode": block.default_approval_mode,
        "mock_kingdee_url": block.mock_kingdee_url,
        "max_tool_rows": block.max_tool_rows,
    }


def _apply(settings: Any, values: dict[str, Any]) -> None:
    merged = {**_read(settings), **values}
    try:
        validated = _GovernanceRuntimeSettings.model_validate(merged)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise SettingsValidationError(f"invalid governance settings: {details}") from exc

    # Validate first, then mutate the live instance in place so objects
    # holding a reference to settings.rag_governance see the change.
    for name in (
        "worker_enabled",
        "worker_poll_seconds",
        "job_max_attempts",
        "default_approval_mode",
        "mock_kingdee_url",
        "max_tool_rows",
    ):
        setattr(settings.rag_governance, name, getattr(validated, name))


GOVERNANCE_SETTINGS_SECTION = SettingsSection(
    key=SECTION_KEY,
    title="RAG governance",
    description=(
        "Background worker cadence and retry policy, the default approval "
        "mode for new projects, and the governed tool result cap."
    ),
    fields=_fields,
    read=_read,
    apply=_apply,
)

register_settings_section(GOVERNANCE_SETTINGS_SECTION)
