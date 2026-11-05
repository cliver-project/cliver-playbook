"""LLM-assisted golden-case generation.

The model proposes; a human confirms. That split is why this module
returns plain ``GoldenCase`` values and writes nothing: candidates only
become a set through the version manager, and only a confirmed set is
used by evaluation.

The prompt asks for strict JSON and the parser is unforgiving. A
generator that emits prose, a fenced code block, an unknown field or a
duplicate id produces an error, not a half-parsed set. The caller may
retry; it must never confirm what it could not read.

Live-data cases need an ``as_of``. The generator is allowed to propose
tool cases (the schema enforces the reference time), but it must never
call a write tool; in the reference implementation it does not call
tools at all — the mock-driven worker (Task 17) fills in expected tool
arguments from a pinned sample period.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence

from pydantic import ValidationError

from cliver_playbook.app.rag.llm.base import LLM
from cliver_playbook.app.rag_governance.golden.schema import GoldenCase
from cliver_playbook.app.rag_governance.models.entities import GovProject
from cliver_playbook.app.rag_governance.stages.base import SourceDocument

_MAX_DOCUMENT_CHARS = 4000
_MAX_TOTAL_CHARS = 20000
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_SYSTEM = (
    "You write golden test cases for a governed RAG project. "
    "Return ONLY a JSON array. No prose, no markdown fences, no comments. "
    "Every element must have: id, question, expected_intent. "
    "Optional fields: expected_strategy (retrieval|tools|agentic|none), "
    "expected_tools, expected_tool_args, as_of (ISO-8601 with offset), "
    "expected_sources (objects with logical_id and optional locator), "
    "expected_answer_facts (short checkable statements), numeric_tolerance, "
    "run_as_clearance, leak_probe_clearance, forbidden_sources, tags, notes. "
    "Use only the source logical ids provided in the prompt. "
    "A case expecting tools MUST include a timezone-aware as_of. "
    "A refusal case must expect no tools and no sources."
)


class GoldenGenerationError(ValueError):
    """The model's output could not be read as golden cases."""


def build_golden_prompt(
    *,
    project: GovProject,
    documents: Sequence[SourceDocument],
    scenario: str = "",
    max_cases: int = 10,
) -> str:
    """The user prompt: the scenario plus bounded document excerpts."""
    excerpts: list[str] = []
    used = 0
    for document in documents:
        text = document.content.decode("utf-8", errors="replace")
        excerpt = text[: min(_MAX_DOCUMENT_CHARS, max(0, _MAX_TOTAL_CHARS - used))]
        if not excerpt:
            break
        used += len(excerpt)
        logical_id = document.metadata.get("logical_id", document.source_uri)
        excerpts.append(f"### source: {logical_id}\n{excerpt}")
        if used >= _MAX_TOTAL_CHARS:
            break

    scenario_text = scenario.strip() or project.description.strip() or project.name
    return (
        f"Project: {project.name}\n"
        f"Scenario: {scenario_text}\n"
        f"Produce at most {max_cases} cases.\n\n"
        "Available sources:\n\n" + "\n\n".join(excerpts)
    )


def parse_generated_cases(raw: str) -> list[GoldenCase]:
    """Parse the model's JSON array, assigning ids when it omitted them."""
    text = raw.strip()
    match = _FENCE.match(text)
    if match is not None:
        text = match.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GoldenGenerationError(f"the model did not return JSON: {exc.msg}") from None
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        payload = payload["cases"]
    if not isinstance(payload, list):
        raise GoldenGenerationError("the model response must be a JSON array of cases")
    if not payload:
        raise GoldenGenerationError("the model returned no cases")

    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for ordinal, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise GoldenGenerationError(f"case {ordinal} is not a JSON object")
        if not item.get("id"):
            item = {**item, "id": f"case-{ordinal:04d}"}
        try:
            case = GoldenCase.model_validate(item)
        except ValidationError as exc:
            invalid = {error["loc"][:1] for error in exc.errors() if error["loc"]}
            raise GoldenGenerationError(
                f"case {item.get('id')!r} is invalid ({sorted(map(str, invalid))}): {exc}"
            ) from None
        if case.id in seen:
            raise GoldenGenerationError(f"duplicate case id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    return cases


async def generate_candidates(
    *,
    project: GovProject,
    documents: Sequence[SourceDocument],
    llm: LLM,
    scenario: str = "",
    max_cases: int = 10,
) -> list[GoldenCase]:
    """Ask the configured model for candidate cases. Writes nothing."""
    if not documents:
        raise GoldenGenerationError("golden generation needs at least one source document")
    prompt = build_golden_prompt(
        project=project,
        documents=documents,
        scenario=scenario,
        max_cases=max_cases,
    )
    raw = await asyncio.to_thread(
        llm.generate,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=4096,
    )
    return parse_generated_cases(raw)


__all__ = [
    "GoldenGenerationError",
    "build_golden_prompt",
    "generate_candidates",
    "parse_generated_cases",
]
