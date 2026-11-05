"""Stage contracts for the governance pipeline.

Every stage follows the rag package's pluggable pattern: a structural
Protocol, a name-keyed registry, at least one offline implementation,
and a Pydantic ``options_model`` so the web UI can render the stage's
configuration without knowing its class.

The stages work on plain values (``SourceDocument``, text, options
objects), not ORM rows. That keeps them unit-testable without a
database and lets the ingestion pipeline decide what to persist. The
rag package's ``Chunker``, ``Embedder``, ``Retriever``, ``Reranker`` and
``LLM`` are reused directly — governance selects them by name, it does
not wrap them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class SourceDocument:
    """One raw document, before cleaning or masking.

    ``content`` stays bytes because a PDF/Word parser needs the
    original; the cleaner returns text. ``source_uri`` is the stable
    human-readable locator used for lineage and dedupe display.
    ``metadata`` carries source-supplied facts (filename, modified
    time, section, classification candidate) that later stages may
    read but must not trust blindly.
    """

    source_uri: str
    title: str
    mime_type: str
    content: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanedText:
    """The cleaner's output: normalized text, ready for masking."""

    text: str


@dataclass(frozen=True)
class MaskingReport:
    """Masked text plus how many of each pattern were replaced.

    The counts are persisted in ingestion stats and re-checked by the
    masking-leak evaluator: a count of zero is evidence, not silence.
    """

    text: str
    counts: dict[str, int]


@dataclass(frozen=True)
class IntentMatch:
    """One intent classifier hit. ``conflict`` resolution belongs to the
    rules engine, not the classifier."""

    intent: str
    confidence: float


class Cleaner(Protocol):
    name: str
    version: str
    options_model: type[BaseModel]

    def clean(self, text: str, options: BaseModel | None = None) -> CleanedText: ...


class Masker(Protocol):
    name: str
    version: str
    options_model: type[BaseModel]

    def mask(self, text: str, options: BaseModel | None = None) -> MaskingReport: ...


class TypeClassifier(Protocol):
    name: str
    version: str
    options_model: type[BaseModel]

    def classify(self, document: SourceDocument, options: BaseModel | None = None) -> str: ...


class Contextualizer(Protocol):
    name: str
    version: str
    options_model: type[BaseModel]

    def contextualize(
        self,
        document: SourceDocument,
        chunk: str,
        options: BaseModel | None = None,
    ) -> str: ...


class Source(Protocol):
    name: str
    version: str
    options_model: type[BaseModel]

    def fetch(self, config: dict[str, Any]) -> Iterator[SourceDocument]: ...


class IntentClassifier(Protocol):
    name: str
    version: str

    def classify(
        self,
        question: str,
        rules: list[Any],
        config: dict[str, Any] | None = None,
    ) -> list[IntentMatch]: ...


class Evaluator(Protocol):
    name: str

    async def evaluate(self, case: Any, ctx: Any) -> Any: ...


class ApprovalPolicy(Protocol):
    name: str

    def requires_approval(self, project: Any, batch: Any) -> bool: ...
