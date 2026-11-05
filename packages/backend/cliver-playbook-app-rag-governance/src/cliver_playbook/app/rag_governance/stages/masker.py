"""Maskers: remove sensitive spans before anything is stored or indexed.

The governing constraint is "only the masked text is persisted" (R9):
masking runs before chunking and embedding, so a raw value never
reaches a parent row, a search representation, an embedding, or a
model prompt. The report's counts go into batch stats and are checked
again by the masking-leak evaluator.

Order matters in the regex masker. The Chinese ID pattern is applied
before the bank-card pattern because an 18-digit ID would otherwise be
counted (and replaced) as a card number; by then the digits are gone,
so the card pass cannot double-count them.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from cliver_playbook.app.rag_governance.stages.base import MaskingReport

PatternName = Literal["phone", "email", "cn_id", "bank_card"]

_PATTERNS: dict[PatternName, re.Pattern[str]] = {
    # Mainland mobile numbers, optionally with a +86 prefix. Boundaries
    # keep a longer digit run from being partially masked.
    "phone": re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # 18-character resident ID: six region digits, a YYYYMMDD date, a
    # three-digit sequence and a digit/X check character.
    "cn_id": re.compile(
        r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
        r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
    ),
    # 16–19 digits, tolerating spaces or hyphens between groups.
    "bank_card": re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)"),
}

# Application order, not user order: the ID pass must precede the card
# pass so overlapping digit runs are counted once.
_DEFAULT_ORDER: tuple[PatternName, ...] = ("phone", "email", "cn_id", "bank_card")


def compiled_patterns(
    names: list[PatternName] | tuple[PatternName, ...] | None = None,
) -> dict[str, re.Pattern[str]]:
    """The named sensitive patterns, for the masking-leak evaluator.

    The evaluator must scan with exactly the patterns the masker applies;
    sharing the compiled table keeps the two from drifting apart.
    """
    selected = _DEFAULT_ORDER if names is None else names
    return {name: _PATTERNS[name] for name in selected if name in _PATTERNS}


class MaskerOptions(BaseModel):
    """Which patterns to apply and what replaces them.

    The defaults cover the categories the financial reference scenario
    needs. A project can narrow the set; it cannot add a regex from the
    API in v1, because a caller-supplied pattern is itself an injection
    surface into stored text.
    """

    patterns: list[PatternName] = Field(default_factory=lambda: list(_DEFAULT_ORDER))
    replacement: str = "[REDACTED]"

    @field_validator("patterns")
    @classmethod
    def _no_duplicates(cls, value: list[PatternName]) -> list[PatternName]:
        if len(set(value)) != len(value):
            raise ValueError("patterns must not repeat")
        if not value:
            raise ValueError("patterns must not be empty")
        return value


class RegexPiiMasker:
    name = "regex-pii"
    version = "1"
    options_model = MaskerOptions

    def mask(self, text: str, options: BaseModel | None = None) -> MaskingReport:
        opts = options if isinstance(options, MaskerOptions) else MaskerOptions()
        working = text
        counts: dict[str, int] = {}
        # Apply in the fixed overlap-safe order, regardless of how the
        # caller listed the selected patterns.
        selected = set(opts.patterns)
        for name in _DEFAULT_ORDER:
            if name not in selected:
                continue
            pattern = _PATTERNS[name]
            working, count = pattern.subn(opts.replacement, working)
            counts[name] = count
        return MaskingReport(text=working, counts=counts)
