"""Intent matching and scope composition.

The offline classifier is deterministic: it matches authored keywords
and regular expressions and scores a rule by how many distinct signals
fired. The score saturates (one signal is 0.5, two 0.75, three 0.875)
so a rule that names many keywords is not penalized when the question
uses only a few of them — the alternative, dividing by the rule's total
signal count, would make long rules nearly unmatchable.

Composition follows design §10 step 4 and R11: the highest-priority
match wins; matches at the same priority are unioned by default. The
project's ``scope_combination`` may widen that to ``union`` or narrow it
to ``intersection``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cliver_playbook.app.rag.filters import And, FilterNode, Or
from cliver_playbook.app.rag_governance.rules.compiler import compile_rule_scope
from cliver_playbook.app.rag_governance.rules.schema import IntentRule

SCOPE_COMBINATIONS: frozenset[str] = frozenset({"highest_priority", "union", "intersection"})


@dataclass(frozen=True)
class IntentMatch:
    """One rule that recognized the question."""

    intent: str
    confidence: float
    rule: IntentRule


class KeywordRegexClassifier:
    """Match authored keywords and regexes; no model call, no state."""

    name = "keyword-regex"
    version = "1"

    def classify(
        self,
        question: str,
        rules: Sequence[IntentRule],
        config: Mapping[str, object] | None = None,
    ) -> list[IntentMatch]:
        defaults = dict(config or {})
        matches: list[IntentMatch] = []
        for rule in rules:
            if rule.classifier.kind != self.name:
                continue
            options = {**defaults, **rule.classifier.config}
            confidence = self._confidence(question, options)
            threshold = float(options.get("threshold", 0.5))
            if confidence is None or confidence < threshold:
                continue
            matches.append(IntentMatch(intent=rule.intent, confidence=confidence, rule=rule))
        return matches

    @staticmethod
    def _confidence(question: str, options: Mapping[str, object]) -> float | None:
        case_sensitive = bool(options.get("case_sensitive", False))
        haystack = question if case_sensitive else question.casefold()
        signals: set[str] = set()

        keywords = options.get("keywords", [])
        for keyword in keywords:  # validated as non-empty strings by the schema
            needle = keyword if case_sensitive else keyword.casefold()
            if needle in haystack:
                signals.add(f"keyword:{needle}")

        patterns = options.get("patterns", [])
        flags = 0 if case_sensitive else re.IGNORECASE
        for pattern in patterns:  # validated as compilable by the schema
            if re.search(pattern, question, flags):
                signals.add(f"pattern:{pattern}")

        if not signals:
            return None
        return 1.0 - 0.5 ** len(signals)


def rank_matches(matches: Sequence[IntentMatch]) -> list[IntentMatch]:
    """Highest priority first, then confidence, then intent for stability."""
    return sorted(
        matches,
        key=lambda match: (-match.rule.priority, -match.confidence, match.intent),
    )


def fallback_rule(rules: Sequence[IntentRule]) -> IntentRule | None:
    """The lowest-priority ``fallback`` rule, if the project declares one."""
    candidates = [rule for rule in rules if rule.intent == "fallback"]
    return min(candidates, key=lambda rule: rule.priority) if candidates else None


def compose_scope(
    matches: Sequence[IntentMatch],
    *,
    scope_combination: str = "highest_priority",
) -> FilterNode | None:
    """Combine the scopes of the selected matches.

    ``highest_priority`` selects only the top-priority group; ``union``
    and ``intersection`` consider every match. Scopes that are empty
    contribute nothing, and a set with no non-empty scope yields
    ``None`` — callers still apply the access predicate unconditionally.
    """
    if scope_combination not in SCOPE_COMBINATIONS:
        raise ValueError(
            f"unknown scope_combination {scope_combination!r}; "
            f"allowed: {', '.join(sorted(SCOPE_COMBINATIONS))}"
        )
    if not matches:
        return None
    if scope_combination == "highest_priority":
        best_priority = max(match.rule.priority for match in matches)
        selected = [match for match in matches if match.rule.priority == best_priority]
    else:
        selected = list(matches)

    scopes = [compile_rule_scope(match.rule) for match in selected]
    nodes = [node for node in scopes if node is not None]
    if not nodes:
        return None
    if len(nodes) == 1:
        return nodes[0]
    return And(tuple(nodes)) if scope_combination == "intersection" else Or(tuple(nodes))
