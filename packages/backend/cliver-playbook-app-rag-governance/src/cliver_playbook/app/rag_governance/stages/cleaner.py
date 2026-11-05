"""Cleaners: text normalization before masking and chunking.

Only ``passthrough`` ships in v1. Normalization is deliberately a stage
rather than an implicit step: a project may need to preserve exact
source text for citation, and silently rewriting whitespace would make
the stored parent differ from the source of record.

An LLM-assisted cleaner would be a new registration, not a change here;
the pipeline selects implementations by name from project config.
"""

from __future__ import annotations

from pydantic import BaseModel

from cliver_playbook.app.rag_governance.stages.base import CleanedText


class CleanerOptions(BaseModel):
    """Options common to cleaner implementations. Empty in v1."""


class PassthroughCleaner:
    name = "passthrough"
    version = "1"
    options_model = CleanerOptions

    def clean(self, text: str, options: BaseModel | None = None) -> CleanedText:
        return CleanedText(text=text)
