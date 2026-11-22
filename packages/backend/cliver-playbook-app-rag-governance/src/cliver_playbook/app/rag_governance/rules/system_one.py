"""Optional System One routing for governance intent rules.

The deterministic keyword classifier remains the default. This router is
for projects whose rule set is large or whose questions phrase the
intent without the authored keywords: a decision model sees the question
and the rule descriptions and returns a probability for every rule.

The router is intentionally fail-open at the call site in the query
facade. A provider error, malformed answer, or empty selection returns
control to the keyword classifier, so a decision-model outage can never
make the governed query surface refuse everything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cliver_core import ModelBinding
from cliver_core.system_one import Choice, ChoiceAnswer

from cliver_playbook.app.rag_governance.rules.engine import IntentMatch
from cliver_playbook.app.rag_governance.rules.schema import IntentRule


class SystemOneRoutingError(ValueError):
    """The decision model did not produce a usable routing answer."""


class SystemOneIntentRouter:
    """Route a question to one or more rules with a System One model.

    The caller owns the binding and its provider lifecycle. Build the
    binding once at application startup (or per run for a loop-bound
    remote provider), pass it here, and keep the router on
    ``app.state.intent_router``. The query facade reads that state and
    falls back to keyword matching on any failure.
    """

    name = "system-one"
    version = "1"

    def __init__(
        self,
        *,
        binding: ModelBinding,
        threshold: float = 0.5,
        timeout: float | None = None,
        max_rules: int = 32,
    ) -> None:
        if binding.purpose not in (None, "system_one"):
            raise ValueError(
                f"SystemOneIntentRouter needs a system_one binding, got purpose {binding.purpose!r}"
            )
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_rules < 1:
            raise ValueError("max_rules must be positive")
        self.binding = binding
        self.threshold = threshold
        self.timeout = timeout
        self.max_rules = max_rules

    async def route(
        self,
        question: str,
        rules: Sequence[IntentRule],
        config: Mapping[str, Any] | None = None,
    ) -> list[IntentMatch]:
        """Return every rule whose probability clears the threshold."""
        candidates = list(rules)
        if not candidates:
            return []
        if len(candidates) > self.max_rules:
            raise SystemOneRoutingError(
                f"rule set has {len(candidates)} rules, above the router limit "
                f"of {self.max_rules}; narrow the rule set or raise max_rules"
            )
        if len(candidates) == 1:
            return [IntentMatch(candidates[0].intent, 1.0, candidates[0])]

        options = dict(config or {})
        threshold = float(options.get("threshold", self.threshold))
        if not 0.0 <= threshold <= 1.0:
            raise SystemOneRoutingError("routing threshold must be in [0, 1]")

        labels = {f"rule-{index}": rule for index, rule in enumerate(candidates)}
        criteria = {
            label: (rule.description.strip() or f"{rule.intent} ({rule.strategy})")
            for label, rule in labels.items()
        }
        choice = Choice(
            instructions=(
                "Select the intent rule that best matches the user's question. "
                "Prefer a specific rule over a fallback; use the description, "
                "not the rule name alone."
            ),
            criteria=criteria,
        )

        provider = self.binding.build_provider()
        call_options = dict(self.binding.call_defaults())
        if self.timeout is not None:
            call_options["timeout"] = self.timeout
        result = await provider.system_one(
            state=question,
            questions={"intent": choice},
            model=self.binding.model,
            **call_options,
        )
        answer = result.answers.get("intent")
        if not isinstance(answer, ChoiceAnswer):
            raise SystemOneRoutingError("System One routing answer is not a choice")

        matches = [
            IntentMatch(
                intent=rule.intent,
                confidence=float(probability),
                rule=rule,
            )
            for label, rule in labels.items()
            if (probability := answer.probabilities.get(label)) is not None
            and probability >= threshold
        ]
        if not matches:
            raise SystemOneRoutingError("no rule cleared the System One routing threshold")
        return sorted(matches, key=lambda match: (-match.confidence, match.intent))


__all__ = ["SystemOneIntentRouter", "SystemOneRoutingError"]
