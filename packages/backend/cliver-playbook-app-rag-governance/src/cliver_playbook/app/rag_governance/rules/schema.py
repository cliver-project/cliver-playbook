"""The intent-rule contract (design §11.1).

A rule maps an intent to three decisions: which corpus the question may
read (``scope``), how the answer is produced (``strategy`` and
``tools``), and how retrieval is tuned. Rules are data, not code: the
scope is a JSON filter AST the compiler validates against the rag
field whitelist, so an authored rule can never inject SQL.

The cross-field rules are the ones a hand-written JSON file gets wrong:
a tool strategy with no tools plans nothing, and a refusal with no
message cannot be shown to the user. Both are rejected here rather than
at query time.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Strategy = Literal["retrieval", "tools", "agentic", "none"]
STRATEGIES: frozenset[str] = frozenset({"retrieval", "tools", "agentic", "none"})
_TOOL_STRATEGIES: frozenset[str] = frozenset({"tools", "agentic"})
INTENT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"


class RuleValidationError(ValueError):
    """A rule or rule set is malformed; nothing was stored."""


class ClassifierSpec(BaseModel):
    """How to recognize the intent.

    ``kind`` selects a classifier implementation; the offline one is
    ``keyword-regex``. Its config accepts ``keywords`` (literal terms,
    matched case-insensitively by default), ``patterns`` (regular
    expressions), ``threshold`` (default 0.5) and ``case_sensitive``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="keyword-regex", min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class RetrievalSpec(BaseModel):
    """Per-rule retrieval tuning; the project config supplies defaults."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["dense", "sparse", "hybrid"] | None = None
    embedder: str | None = Field(default=None, max_length=128)
    top_k: int | None = Field(default=None, ge=1, le=200)
    rerank_top_k: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def _rerank_within_top_k(self) -> RetrievalSpec:
        if (
            self.top_k is not None
            and self.rerank_top_k is not None
            and self.rerank_top_k > self.top_k
        ):
            raise ValueError("rerank_top_k cannot exceed top_k")
        return self


class RefusalSpec(BaseModel):
    """The terminal message for a ``none``-strategy rule."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class IntentRule(BaseModel):
    """One intent -> scope + strategy decision."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=128, pattern=INTENT_PATTERN)
    description: str = Field(default="", max_length=4000)
    priority: int = Field(default=100, ge=0, le=10_000)
    classifier: ClassifierSpec = Field(default_factory=ClassifierSpec)
    scope: dict[str, Any] = Field(default_factory=dict)
    retrieval: RetrievalSpec = Field(default_factory=RetrievalSpec)
    strategy: Strategy = "retrieval"
    tools: list[str] = Field(default_factory=list)
    snapshot_fallback: bool = False
    refusal: RefusalSpec | None = None

    @model_validator(mode="after")
    def _strategy_contract(self) -> IntentRule:
        if self.strategy in _TOOL_STRATEGIES and not self.tools:
            raise ValueError(f"strategy {self.strategy!r} requires at least one tool")
        if self.strategy not in _TOOL_STRATEGIES and self.tools:
            raise ValueError(f"strategy {self.strategy!r} cannot declare tools")
        if self.strategy == "none" and self.refusal is None:
            raise ValueError("a none-strategy rule requires a refusal message")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("tools must not repeat a tool name")
        return self

    @model_validator(mode="after")
    def _keyword_classifier_config(self) -> IntentRule:
        if self.classifier.kind != "keyword-regex":
            return self
        config = self.classifier.config
        for key in ("keywords", "patterns"):
            values = config.get(key, [])
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError(f"classifier {key} must be a list of non-empty strings")
        for pattern in config.get("patterns", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid classifier pattern {pattern!r}: {exc}") from None
        threshold = config.get("threshold", 0.5)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise TypeError("classifier threshold must be a number")
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError("classifier threshold must be between 0 and 1")
        if "case_sensitive" in config and not isinstance(config["case_sensitive"], bool):
            raise ValueError("classifier case_sensitive must be a boolean")
        return self
