"""System One intent routing: typed prediction with keyword fallback.

The router is optional and fail-open: a malformed answer, timeout or
provider error must leave the deterministic keyword classifier in charge.
"""

from __future__ import annotations

import pytest
from cliver_core import ModelBinding
from cliver_core.system_one import ChoiceAnswer, SystemOneResult

from cliver_playbook.app.rag_governance.rules.schema import IntentRule
from cliver_playbook.app.rag_governance.rules.system_one import (
    SystemOneIntentRouter,
    SystemOneRoutingError,
)


class _FakeProvider:
    def __init__(self, answer) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    async def system_one(self, *, state, questions, model, **options):
        self.calls.append(
            {"state": state, "questions": questions, "model": model, "options": options}
        )
        if isinstance(self.answer, Exception):
            raise self.answer
        return SystemOneResult(answers={"intent": self.answer})


def _rules() -> list[IntentRule]:
    return [
        IntentRule.model_validate(
            {
                "intent": "archive_retention",
                "description": "Archive retention periods and disposal.",
                "priority": 100,
                "strategy": "retrieval",
            }
        ),
        IntentRule.model_validate(
            {
                "intent": "finance_report",
                "description": "Financial reports and accounting metrics.",
                "priority": 90,
                "strategy": "retrieval",
            }
        ),
    ]


async def test_router_returns_every_rule_above_the_threshold() -> None:
    provider = _FakeProvider(
        ChoiceAnswer(
            choice="rule-0",
            probabilities={"rule-0": 0.81, "rule-1": 0.19},
        )
    )
    router = SystemOneIntentRouter(
        binding=ModelBinding.system_one(provider=provider, model="fake-system-one"),
        threshold=0.2,
    )

    matches = await router.route("档案保管期限是多久？", _rules())

    assert [match.intent for match in matches] == ["archive_retention"]
    assert matches[0].confidence == pytest.approx(0.81)
    call = provider.calls[0]
    assert call["model"] == "fake-system-one"
    assert call["state"] == "档案保管期限是多久？"
    question = call["questions"]["intent"]
    assert question.criteria == {
        "rule-0": "Archive retention periods and disposal.",
        "rule-1": "Financial reports and accounting metrics.",
    }


async def test_router_rejects_a_non_choice_answer() -> None:
    provider = _FakeProvider(SystemOneResult(answers={"intent": object()}).answers["intent"])
    router = SystemOneIntentRouter(
        binding=ModelBinding.system_one(provider=provider, model="fake"),
    )

    with pytest.raises(SystemOneRoutingError, match="choice"):
        await router.route("question", _rules())


async def test_router_rejects_a_result_without_a_match() -> None:
    provider = _FakeProvider(
        ChoiceAnswer(choice="rule-0", probabilities={"rule-0": 0.1, "rule-1": 0.1})
    )
    router = SystemOneIntentRouter(
        binding=ModelBinding.system_one(provider=provider, model="fake"),
        threshold=0.5,
    )

    with pytest.raises(SystemOneRoutingError, match="threshold"):
        await router.route("question", _rules())


async def test_router_propagates_provider_errors_for_the_facade_fallback() -> None:
    provider = _FakeProvider(RuntimeError("provider down"))
    router = SystemOneIntentRouter(
        binding=ModelBinding.system_one(provider=provider, model="fake"),
    )

    with pytest.raises(RuntimeError, match="provider down"):
        await router.route("question", _rules())
