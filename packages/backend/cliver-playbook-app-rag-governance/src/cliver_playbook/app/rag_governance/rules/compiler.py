"""Compile a rule's JSON scope into the rag filter AST.

The JSON shape is the one in design §11.2: boolean nodes ``and``/
``or``/``not`` and leaves ``{field, op, value}``. The rag compiler owns
the field whitelist and value binding, so this module only translates
the tree and wraps its errors with the rule's intent. Compiling eagerly
during rule preview and activation means a mistyped field is caught
before a query ever runs.
"""

from __future__ import annotations

from typing import Any

from cliver_playbook.app.rag.filters import (
    And,
    FieldFilter,
    FilterCompileError,
    FilterNode,
    Not,
    Or,
    compile_filter,
)
from cliver_playbook.app.rag_governance.rules.schema import IntentRule

_LEAF_KEYS = frozenset({"field", "op", "value"})


class RuleCompileError(ValueError):
    """A rule scope is not a valid filter AST."""


def _parse_node(payload: Any, path: str) -> FilterNode:
    if not isinstance(payload, dict):
        raise RuleCompileError(f"{path}: a filter node must be a JSON object")
    if "field" in payload:
        unknown = set(payload) - _LEAF_KEYS
        if unknown:
            raise RuleCompileError(f"{path}: unknown leaf key(s): {', '.join(sorted(unknown))}")
        if "op" not in payload:
            raise RuleCompileError(f"{path}: a leaf needs an op")
        if not isinstance(payload["field"], str) or not isinstance(payload["op"], str):
            raise RuleCompileError(f"{path}: field and op must be strings")
        try:
            return FieldFilter(field=payload["field"], op=payload["op"], value=payload.get("value"))
        except FilterCompileError as exc:
            raise RuleCompileError(f"{path}: {exc}") from None
    if len(payload) != 1:
        raise RuleCompileError(
            f"{path}: a boolean node must have exactly one of 'and', 'or', 'not'"
        )
    key, child = next(iter(payload.items()))
    if key in ("and", "or"):
        if not isinstance(child, list) or not child:
            raise RuleCompileError(f"{path}.{key}: expected a non-empty array")
        children = tuple(
            _parse_node(item, f"{path}.{key}[{index}]") for index, item in enumerate(child)
        )
        return And(children) if key == "and" else Or(children)
    if key == "not":
        return Not(_parse_node(child, f"{path}.not"))
    raise RuleCompileError(f"{path}: unknown node {key!r}; expected 'and', 'or', 'not' or a leaf")


def parse_filter_ast(payload: dict[str, Any] | None) -> FilterNode | None:
    """Translate a JSON scope; an empty object means "no rule scope"."""
    if not payload:
        return None
    return _parse_node(payload, "scope")


def compile_rule_scope(rule: IntentRule) -> FilterNode | None:
    """The rule's scope as rag filter nodes, validated against its whitelist."""
    node = parse_filter_ast(rule.scope)
    if node is not None:
        try:
            compile_filter(node)
        except FilterCompileError as exc:
            raise RuleCompileError(f"rule {rule.intent!r}: {exc}") from None
    return node
