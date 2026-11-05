"""What one query run looked like, independent of how it was produced.

Evaluators must be able to judge a run without importing the query
facade, and the facade must be able to build this shape without
importing the evaluators. The observation is therefore a plain value:
retrieved documents, citations, tool calls, context text and the answer.

Tool calls carry their policy facts explicitly (``read_only``, ``bound``,
``authorized``) instead of requiring the evaluator to re-derive them.
A missing ``as_of`` stays ``None`` on purpose: it is the evidence that
the reference time was not propagated, which is precisely what the
freshness and routing evaluators need to see.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ObservedSource:
    """A document that reached the retrieval result or the answer."""

    logical_id: str
    locator: str | None = None
    classification: int | None = None
    text: str = ""


@dataclass(frozen=True)
class ObservedCitation:
    """A citation the answer made: a document locator or a tool result."""

    kind: str
    ref: str
    locator: str | None = None


@dataclass(frozen=True)
class ObservedToolCall:
    """One tool invocation and the policy flags it ran under."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    as_of: datetime | None = None
    read_only: bool = True
    bound: bool = True
    authorized: bool = True
    min_clearance: int | None = None
    error: str | None = None
    result: Any = None
    is_snapshot: bool = False
    period: str | None = None


@dataclass(frozen=True)
class QueryObservation:
    """The complete, evaluator-readable trace of one query."""

    question: str = ""
    intent: str | None = None
    strategy: str = "retrieval"
    answer: str = ""
    refused: bool = False
    retrieval_calls: int = 0
    sources: tuple[ObservedSource, ...] = ()
    citations: tuple[ObservedCitation, ...] = ()
    tool_calls: tuple[ObservedToolCall, ...] = ()
    # Search text, chunk text, parent text and any other stored context.
    contexts: tuple[str, ...] = ()
    # (parent text, contextual text) pairs for the fidelity evaluator.
    contextual_pairs: tuple[tuple[str, str], ...] = ()
    unavailability_answer: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def scanned_texts(self) -> list[str]:
        """Every text the masking and access evaluators must scan."""
        texts: list[str] = [self.answer, *self.contexts]
        texts.extend(source.text for source in self.sources if source.text)
        for call in self.tool_calls:
            if call.args:
                texts.append(json.dumps(call.args, ensure_ascii=False, default=str))
            if call.result is not None:
                texts.append(json.dumps(call.result, ensure_ascii=False, default=str))
        return [text for text in texts if text]
