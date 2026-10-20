"""Tests for shared table rendering and row-safe splitting."""

from __future__ import annotations

from cliver_playbook.app.rag.chunking.tables import (
    TableData,
    render_table,
    table_text_parts,
)


def test_markdown_rendering_escapes_and_pads() -> None:
    table = TableData(
        caption="Totals",
        header_rows=[["name", "amount"]],
        body_rows=[["a|b", "1\n2"], ["short"]],
    )

    rendered = render_table(table)

    assert rendered.startswith("Totals\n\n| name | amount |")
    assert r"a\|b" in rendered
    assert "1<br>2" in rendered
    assert "| short |  |" in rendered


def test_html_rendering_escapes_cells() -> None:
    table = TableData(
        caption="A & B",
        header_rows=[["name", "value"]],
        body_rows=[["<script>", "1&2"]],
    )

    rendered = render_table(table, table_format="html")

    assert "<caption>A &amp; B</caption>" in rendered
    assert "<th>name</th><th>value</th>" in rendered
    assert "<td>&lt;script&gt;</td>" in rendered
    assert "<td>1&amp;2</td>" in rendered
    assert "<thead>" in rendered
    assert "<tbody>" in rendered


def test_oversized_table_splits_by_rows_and_repeats_header() -> None:
    table = TableData(
        caption="Totals",
        header_rows=[["name", "amount"]],
        body_rows=[[f"item-{index}", str(index)] for index in range(10)],
    )

    parts = table_text_parts(table, chunk_size=80, table_format="markdown")

    assert len(parts) > 1
    for part in parts:
        assert part.startswith("Totals")
        assert "| name | amount |" in part
    joined = "\n".join(parts)
    for index in range(10):
        assert f"item-{index}" in joined
        assert joined.count(f"item-{index}") == 1


def test_table_without_body_rows_is_one_part() -> None:
    table = TableData(caption="Empty", header_rows=[["name"]], body_rows=[])

    assert table_text_parts(table, chunk_size=10) == ["Empty\n\n| name |\n| --- |"]


def test_table_without_header_keeps_data_rows() -> None:
    table = TableData(body_rows=[["alpha", "1"], ["beta", "2"]])

    rendered = render_table(table)

    assert "| alpha | 1 |" in rendered
    assert "| beta | 2 |" in rendered


def test_single_oversized_row_stays_atomic() -> None:
    table = TableData(header_rows=[["name"]], body_rows=[["x" * 500]])

    parts = table_text_parts(table, chunk_size=50)

    assert len(parts) == 1
    assert "x" * 500 in parts[0]
