"""Application settings for the ``rag_governance`` package.

Extends the RAG package's Settings with one ``rag_governance`` block.
The default approval mode is project configuration, not a process-wide
policy: this value is only the default used when a project is created
without an explicit mode, and an existing project keeps its recorded
mode.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cliver_playbook.app.basic.runtime import lazy_settings
from cliver_playbook.app.rag.settings import Settings as RagSettings


class GovernanceSettings(BaseModel):
    """Runtime knobs the governance workers and tool layer read."""

    worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1)
    default_approval_mode: str = "manual"
    # Empty means "no mock server configured"; the finance acceptance
    # suite wires the in-process transport instead of this URL.
    mock_kingdee_url: str = ""
    max_tool_rows: int = Field(default=1000, ge=1)


class Settings(RagSettings):
    """RAG settings plus the governance block."""

    rag_governance: GovernanceSettings = Field(default_factory=GovernanceSettings)


# Process-aware proxy: resolves to the runtime-bound composed Settings
# instance, or to a lazily built Settings() of this class.
settings = lazy_settings(Settings)


def get_settings() -> Settings:
    """Return the process-wide Settings instance (see ``settings`` above)."""
    return settings.resolve()
