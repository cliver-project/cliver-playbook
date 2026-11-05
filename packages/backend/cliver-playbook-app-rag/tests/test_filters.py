"""The typed filter AST: composition, field whitelist, bound values.

The AST is the only way a caller narrows retrieval. Compiling it to
SQLAlchemy expressions (rather than building SQL strings in the
governance package) is what keeps user-supplied filter values out of
the SQL text and keeps the allow-listed field set in one place.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from cliver_playbook.app.rag.filters import (
    And,
    FieldFilter,
    FilterCompileError,
    FilterOp,
    Not,
    Or,
    compile_filter,
)


def test_field_filter_binds_the_value() -> None:
    expr = compile_filter(FieldFilter("doc_type", FilterOp.EQ, "policy"))
    compiled = expr.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "rag_documents.metadata" in sql
    assert "policy" not in sql  # bound, not interpolated
    assert "doc_type" in compiled.params.values()


def test_and_or_not_compose() -> None:
    node = And(
        (
            FieldFilter("collection_id", FilterOp.EQ, "finance-kpi"),
            Or(
                (
                    FieldFilter("classification", FilterOp.LTE, 3),
                    Not(FieldFilter("source_uri", FilterOp.EQ, "secret.md")),
                )
            ),
        )
    )
    assert compile_filter(node) is not None


def test_direct_column_fields_compile() -> None:
    expr = compile_filter(
        And(
            (
                FieldFilter("classification", FilterOp.GTE, 2),
                FieldFilter("title", FilterOp.CONTAINS, "营收"),
            )
        )
    )
    sql = str(expr.compile(dialect=postgresql.dialect()))
    assert "rag_documents.classification" in sql
    assert "rag_documents.title" in sql


def test_in_rejects_an_empty_list() -> None:
    with pytest.raises(FilterCompileError):
        compile_filter(FieldFilter("doc_type", FilterOp.IN, []))


def test_in_rejects_a_non_list() -> None:
    with pytest.raises(FilterCompileError):
        compile_filter(FieldFilter("doc_type", FilterOp.IN, "policy"))


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(FilterCompileError):
        compile_filter(FieldFilter("password", FilterOp.EQ, "x"))


def test_unknown_operator_is_rejected() -> None:
    with pytest.raises(FilterCompileError):
        FieldFilter("doc_type", "matches_regex", "policy")


def test_none_compiles_to_none() -> None:
    assert compile_filter(None) is None
