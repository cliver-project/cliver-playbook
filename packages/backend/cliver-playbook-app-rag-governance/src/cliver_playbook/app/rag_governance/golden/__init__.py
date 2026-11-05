"""Golden datasets: schema, JSONL codec, generation and versioning."""

from cliver_playbook.app.rag_governance.golden.generator import (
    GoldenGenerationError,
    build_golden_prompt,
    generate_candidates,
    parse_generated_cases,
)
from cliver_playbook.app.rag_governance.golden.jsonl import dump_jsonl, parse_jsonl
from cliver_playbook.app.rag_governance.golden.schema import (
    ExpectedSource,
    GoldenCase,
    GoldenValidationError,
    Strategy,
)
from cliver_playbook.app.rag_governance.golden.versions import (
    GOLDEN_SOURCES,
    GoldenSetNotFoundError,
    GoldenVersionError,
    confirm_set,
    create_candidate_set,
    fork_set,
    get_set,
    get_set_or_raise,
    list_sets,
    load_cases,
    replace_cases,
    update_case,
)

__all__ = [
    "GOLDEN_SOURCES",
    "ExpectedSource",
    "GoldenCase",
    "GoldenGenerationError",
    "GoldenSetNotFoundError",
    "GoldenValidationError",
    "GoldenVersionError",
    "Strategy",
    "build_golden_prompt",
    "confirm_set",
    "create_candidate_set",
    "dump_jsonl",
    "fork_set",
    "generate_candidates",
    "get_set",
    "get_set_or_raise",
    "list_sets",
    "load_cases",
    "parse_generated_cases",
    "parse_jsonl",
    "replace_cases",
    "update_case",
]
