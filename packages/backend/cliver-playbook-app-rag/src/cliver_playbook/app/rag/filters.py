"""Typed retrieval filters, compiled to SQLAlchemy expressions.

Callers never send SQL. They send an AST over a small allow-listed field
set; this module resolves each field to an expression and lets
SQLAlchemy bind every value. Two consequences matter:

- A value can never change the shape of the query, so the AST is safe
  to accept from a project's intent-rule configuration.
- The field whitelist is the contract. Adding a new searchable field is
  one entry here, and a filter naming anything else fails before a
  query runs.

Document-level fields live on ``rag_documents``. Fields that vary by
corpus (``doc_type``, ``tags``, ``effective_date``) live in the
document's JSONB ``metadata`` column, addressed with a bound key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, and_, false, not_, or_

from cliver_playbook.app.rag.models.entities import Document


class FilterCompileError(ValueError):
    """A filter names an unknown field/operator or has an invalid value."""


class FilterOp(StrEnum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    EXISTS = "exists"


@dataclass(frozen=True)
class FieldFilter:
    """A predicate over one allow-listed field."""

    field: str
    op: FilterOp | str
    value: Any = None

    def __post_init__(self) -> None:
        if self.field not in _FIELDS:
            raise FilterCompileError(
                f"unknown filter field {self.field!r}; allowed: {', '.join(sorted(_FIELDS))}"
            )
        try:
            object.__setattr__(self, "op", FilterOp(self.op))
        except ValueError:
            raise FilterCompileError(
                f"unknown filter operator {self.op!r}; "
                f"allowed: {', '.join(op.value for op in FilterOp)}"
            ) from None


@dataclass(frozen=True)
class And:
    children: tuple[FilterNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", tuple(self.children))
        if not self.children:
            raise FilterCompileError("And requires at least one child")


@dataclass(frozen=True)
class Or:
    children: tuple[FilterNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", tuple(self.children))
        if not self.children:
            raise FilterCompileError("Or requires at least one child")


@dataclass(frozen=True)
class Not:
    child: FilterNode


FilterNode = FieldFilter | And | Or | Not


def _json_text(field: str) -> ColumnElement[Any]:
    """A JSONB metadata value coerced to text for comparison."""
    return Document.metadata_json[field].as_string()


# Each resolver returns an expression WITHOUT the operator applied; the
# operator decides how the column is used.
_FIELDS: dict[str, Callable[[], ColumnElement[Any]]] = {
    "doc_type": lambda: _json_text("doc_type"),
    "tags": lambda: Document.metadata_json["tags"],
    "effective_date": lambda: _json_text("effective_date"),
    "classification": lambda: Document.classification,
    "collection_id": lambda: Document.collection_id,
    "source_uri": lambda: Document.source_uri,
    "logical_id": lambda: Document.logical_id,
    "title": lambda: Document.title,
}


def _compile_field(node: FieldFilter) -> ColumnElement[bool]:
    column = _FIELDS[node.field]()
    op = FilterOp(node.op)
    value = node.value

    if op in (FilterOp.IN, FilterOp.NOT_IN):
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise FilterCompileError(f"{node.field}: {op.value} needs a list value")
        values = list(value)
        if not values:
            raise FilterCompileError(f"{node.field}: {op.value} needs a non-empty list")
        return column.in_(values) if op is FilterOp.IN else column.not_in(values)

    if op is FilterOp.EXISTS:
        return column.is_not(None)

    if value is None:
        raise FilterCompileError(f"{node.field}: {op.value} needs a value")

    if op is FilterOp.EQ:
        return column == value
    if op is FilterOp.NE:
        return column != value
    if op is FilterOp.GT:
        return column > value
    if op is FilterOp.GTE:
        return column >= value
    if op is FilterOp.LT:
        return column < value
    if op is FilterOp.LTE:
        return column <= value
    # CONTAINS: JSONB array containment for tags (value may be a scalar
    # or a list), substring match for text columns.
    if node.field == "tags":
        needle = value if isinstance(value, (list, tuple)) else [value]
        return column.contains(needle)
    return column.contains(value)


def compile_filter(node: FilterNode | None) -> ColumnElement[bool] | None:
    """Compile an AST to a SQLAlchemy boolean expression, or ``None``."""
    if node is None:
        return None
    if isinstance(node, FieldFilter):
        return _compile_field(node)
    if isinstance(node, And):
        return and_(*(compile_filter(child) for child in node.children))
    if isinstance(node, Or):
        return or_(*(compile_filter(child) for child in node.children))
    if isinstance(node, Not):
        child = compile_filter(node.child)
        return not_(child) if child is not None else false()
    raise FilterCompileError(f"unsupported filter node: {type(node).__name__}")
