"""Tool routing and the structural tool-safety gates.

Two classes of finding share this evaluator:

- **Hard** — a write tool was called, a tool was called without being
  bound to the project or authorized for the caller, or a ``none``-
  strategy case performed retrieval/tool work at all. These fail the
  run regardless of thresholds.
- **Soft** — the strategy, tool selection or arguments differ from the
  case's expectation. These fail the case and feed the configurable
  routing-accuracy metric.

``as_of`` propagation is soft by itself, but combined with freshness it
is what prevents a live answer from silently using yesterday's numbers.
"""

from __future__ import annotations

from datetime import UTC

from cliver_playbook.app.rag_governance.evaluation.context import EvalContext
from cliver_playbook.app.rag_governance.evaluation.report import (
    CaseResult,
    skipped_result,
)
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase


def _same_instant(first, second) -> bool:
    try:
        return first.astimezone(UTC) == second.astimezone(UTC)
    except (AttributeError, ValueError):
        return first == second


class ToolRoutingEvaluator:
    name = "tool-routing"
    hard_gate = False

    async def evaluate(self, case: GoldenCase, ctx: EvalContext) -> CaseResult:
        observation = ctx.observation
        if observation is None:
            return skipped_result(case.id, self.name, "no query observation")

        expected_strategy = case.resolved_strategy()
        soft: list[str] = []
        hard: list[str] = []

        if expected_strategy == "none":
            if observation.retrieval_calls:
                hard.append(
                    f"none-strategy case performed {observation.retrieval_calls} retrieval call(s)"
                )
            if observation.tool_calls:
                hard.append(
                    f"none-strategy case performed {len(observation.tool_calls)} tool call(s)"
                )
            if observation.strategy != "none":
                soft.append(f"expected strategy 'none', observed {observation.strategy!r}")
        else:
            allowed = set(case.allowed_strategies) | {expected_strategy}
            if observation.strategy not in allowed:
                soft.append(
                    f"observed strategy {observation.strategy!r} is not in {sorted(allowed)}"
                )

        for call in observation.tool_calls:
            if not call.read_only:
                hard.append(f"write tool called: {call.name}")
            if not call.bound:
                hard.append(f"unbound tool called: {call.name}")
            if not call.authorized:
                hard.append(f"unauthorized tool called: {call.name}")

        expected_tools = set(case.expected_tools)
        observed_tools = {call.name for call in observation.tool_calls}
        missing = sorted(expected_tools - observed_tools)
        unexpected = sorted(observed_tools - expected_tools)
        if missing:
            soft.append(f"expected tool(s) not called: {', '.join(missing)}")
        if unexpected:
            soft.append(f"unexpected tool(s) called: {', '.join(unexpected)}")

        for name, expected_args in case.expected_tool_args.items():
            calls = [call for call in observation.tool_calls if call.name == name]
            if not calls:
                continue
            actual = calls[0].args
            for key, expected_value in expected_args.items():
                if key not in actual:
                    soft.append(f"tool {name!r} was called without argument {key!r}")
                elif actual[key] != expected_value:
                    soft.append(
                        f"tool {name!r} argument {key!r} was {actual[key]!r}, "
                        f"expected {expected_value!r}"
                    )

        if case.as_of is not None:
            for call in observation.tool_calls:
                if call.as_of is None:
                    soft.append(f"tool {call.name!r} did not receive as_of")
                elif not _same_instant(call.as_of, case.as_of):
                    soft.append(
                        f"tool {call.name!r} received as_of {call.as_of.isoformat()}, "
                        f"expected {case.as_of.isoformat()}"
                    )

        violations = [*soft, *hard]
        return CaseResult(
            case_id=case.id,
            evaluator=self.name,
            passed=not violations,
            metrics={"routing_accuracy": 1.0 if not violations else 0.0},
            violations=violations,
            hard_violations=hard,
            detail={
                "expected_strategy": expected_strategy,
                "observed_strategy": observation.strategy,
            },
        )
