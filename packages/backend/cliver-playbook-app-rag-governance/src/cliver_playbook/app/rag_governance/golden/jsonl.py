"""Golden JSONL codec: one validated case per line.

The format is the interchange and review surface the product brief
asks for: a human can open the file, edit one row, and re-import it.
That is only safe if import is all-or-nothing: a partial import would
leave a confirmed set missing exactly the rows whose parse failed.
This codec therefore validates every line before returning anything.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from pydantic import ValidationError

from cliver_playbook.app.rag_governance.golden.schema import (
    GoldenCase,
    GoldenValidationError,
)


def parse_jsonl(text: str) -> list[GoldenCase]:
    """Parse and validate a whole JSONL document, or raise.

    Blank lines are ignored. Case ids must be unique within the
    document; a duplicate would make ``update_case`` and evaluation
    reports ambiguous.
    """
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = GoldenCase.model_validate_json(line)
        except ValidationError as exc:
            raise GoldenValidationError(f"line {line_number}: {exc}") from None
        if case.id in seen:
            raise GoldenValidationError(f"line {line_number}: duplicate case id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise GoldenValidationError("the JSONL document contains no cases")
    return cases


def dump_jsonl(cases: Iterable[GoldenCase]) -> str:
    """Serialize cases sorted by id, one compact JSON object per line."""
    lines: list[str] = []
    for case in sorted(cases, key=lambda item: item.id):
        payload = case.model_dump(mode="json")
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "".join(f"{line}\n" for line in lines)
