"""The golden-case contract (design §12.1).

A case is a question plus the facts a correct answer must satisfy. It
is deliberately not a reference answer: exact wording is a poor target
(a correct answer may phrase the same fact differently), while intents,
source locators, tool routing, numeric facts and refusal behaviour are
checkable. The human confirms the cases; the evaluator asserts them.

``extra="forbid"`` is the load-bearing setting. A JSONL import that
silently dropped a misspelled field would confirm a case that asserts
less than its author intended, and the evaluation would report a false
pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Strategy = Literal["retrieval", "tools", "agentic", "none"]

CASE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_REFUSAL_TAGS: frozenset[str] = frozenset({"refusal", "write-refusal"})


class GoldenValidationError(ValueError):
    """A golden case or document is malformed; nothing was stored."""


class ExpectedSource(BaseModel):
    """A logical locator expected among the retrieved sources.

    ``logical_id`` is the stable document identity, never a storage id:
    re-ingesting a document changes its row id but not its logical id
    (R6). ``locator`` narrows the expectation to a section or metric.
    """

    model_config = ConfigDict(extra="forbid")

    logical_id: str = Field(min_length=1, max_length=128)
    locator: str | None = Field(default=None, max_length=256)


class GoldenCase(BaseModel):
    """One test case. See design §12.1 for field semantics."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=CASE_ID_PATTERN)
    question: str = Field(min_length=1, max_length=4000)
    expected_intent: str = Field(min_length=1, max_length=128)

    # Optional: derived from the expected surface when omitted, so a
    # hand-written JSONL line stays short.
    expected_strategy: Strategy | None = None
    allowed_strategies: list[Strategy] = Field(default_factory=list)

    expected_tools: list[str] = Field(default_factory=list)
    expected_tool_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # The reference instant the question is asked, not the data cutoff.
    # Required when tools are expected: a live case must never run
    # against an implicit "now".
    as_of: datetime | None = None

    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    expected_answer_facts: list[str] = Field(default_factory=list)
    numeric_tolerance: float = Field(default=0.005, ge=0.0, le=1.0)
    run_as_clearance: int = Field(default=0, ge=0, le=5)
    leak_probe_clearance: int | None = Field(default=None, ge=0, le=5)
    forbidden_sources: list[str] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)

    @field_validator("as_of")
    @classmethod
    def _aware_as_of(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @field_validator("expected_answer_facts")
    @classmethod
    def _non_empty_facts(cls, value: list[str]) -> list[str]:
        if any(not fact.strip() for fact in value):
            raise ValueError("expected_answer_facts must not contain empty strings")
        return value

    @field_validator("tags")
    @classmethod
    def _bounded_tags(cls, value: list[str]) -> list[str]:
        if any(len(tag) > 64 for tag in value):
            raise ValueError("tags must be at most 64 characters")
        return value

    @model_validator(mode="after")
    def _cross_field_rules(self) -> GoldenCase:
        if self.expected_tools and self.as_of is None:
            raise ValueError("as_of is required when expected_tools is non-empty")
        unknown_args = sorted(set(self.expected_tool_args) - set(self.expected_tools))
        if unknown_args:
            raise ValueError(
                "expected_tool_args names tools not in expected_tools: " + ", ".join(unknown_args)
            )
        if (
            self.expected_strategy is not None
            and self.allowed_strategies
            and self.expected_strategy not in self.allowed_strategies
        ):
            raise ValueError("expected_strategy must be one of allowed_strategies")
        strategy = self.resolved_strategy()
        if strategy == "none" and (self.expected_tools or self.expected_sources):
            raise ValueError("a none-strategy case must expect zero tools and zero sources")
        return self

    def resolved_strategy(self) -> Strategy:
        """The expected strategy, derived when the case omitted it."""
        if self.expected_strategy is not None:
            return self.expected_strategy
        if _REFUSAL_TAGS & set(self.tags):
            return "none"
        if not self.expected_tools:
            return "retrieval"
        return "agentic" if self.expected_sources else "tools"
