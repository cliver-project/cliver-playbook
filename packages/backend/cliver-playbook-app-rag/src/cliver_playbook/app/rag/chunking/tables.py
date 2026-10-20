"""Table extraction and rendering shared by the DOCX and HTML chunkers.

Both parsers produce a :class:`TableData` and hand it to this module,
so a table looks the same in a chunk whether it came from Word or
HTML. Two formats are supported:

* ``markdown`` — pipe table, the default because it is compact and
  reads naturally in retrieval context;
* ``html`` — escaped ``<table>`` markup, useful when downstream
  consumers want the row/column structure preserved.

Oversized tables are split by whole body rows: a chunk never starts
or ends in the middle of a row. The caption and header are repeated
in every part so each part remains understandable on its own. A
single row larger than ``chunk_size`` stays atomic here; the caller
may split that row afterwards with the recursive splitter.

Cell contents are treated as plain text. Spans and merged cells are
not expanded (DOCX merged cells repeat their text through
``row.cells``, which keeps column alignment); a parser that needs
more structure should flatten it before constructing ``TableData``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Literal

TableFormat = Literal["markdown", "html"]


@dataclass
class TableData:
    """A table in document order.

    ``header_rows`` normally has zero or one entry. Markdown rendering
    uses the first header row as the table header and emits any extra
    header rows as body rows; HTML rendering keeps all of them inside
    ``<thead>``.
    """

    caption: str = ""
    header_rows: list[list[str]] = field(default_factory=list)
    body_rows: list[list[str]] = field(default_factory=list)


def _normalize_cell(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _markdown_cell(value: str) -> str:
    return _normalize_cell(value).replace("|", "\\|").replace("\n", "<br>")


def _html_cell(value: str) -> str:
    return escape(_normalize_cell(value)).replace("\n", "<br>")


def _row_width(rows: list[list[str]]) -> int:
    return max((len(row) for row in rows), default=0)


def _render_markdown(table: TableData) -> str:
    width = _row_width(table.header_rows + table.body_rows)
    if width == 0:
        return table.caption.strip()

    header_row = table.header_rows[0] if table.header_rows else [""] * width
    header = [_markdown_cell(value) for value in header_row]
    header += [""] * (width - len(header))

    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")

    extra_headers = table.header_rows[1:] if table.header_rows else []
    for row in [*extra_headers, *table.body_rows]:
        cells = [_markdown_cell(value) for value in row]
        cells += [""] * (width - len(cells))
        lines.append("| " + " | ".join(cells) + " |")

    rendered = "\n".join(lines)
    caption = table.caption.strip()
    return f"{caption}\n\n{rendered}" if caption else rendered


def _render_html(table: TableData) -> str:
    lines = ["<table>"]
    caption = table.caption.strip()
    if caption:
        lines.append(f"<caption>{_html_cell(caption)}</caption>")
    if table.header_rows:
        lines.append("<thead>")
        for row in table.header_rows:
            cells = "".join(f"<th>{_html_cell(value)}</th>" for value in row)
            lines.append(f"<tr>{cells}</tr>")
        lines.append("</thead>")
    if table.body_rows:
        lines.append("<tbody>")
        for row in table.body_rows:
            cells = "".join(f"<td>{_html_cell(value)}</td>" for value in row)
            lines.append(f"<tr>{cells}</tr>")
        lines.append("</tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def render_table(table: TableData, *, table_format: TableFormat = "markdown") -> str:
    """Render one table as markdown or HTML text."""
    if table_format == "html":
        return _render_html(table)
    return _render_markdown(table)


def table_text_parts(
    table: TableData,
    *,
    chunk_size: int,
    table_format: TableFormat = "markdown",
) -> list[str]:
    """Render a table, splitting oversized tables by whole body rows.

    Every part repeats the caption and header. The algorithm renders
    candidate parts instead of estimating widths, so escape sequences
    and multi-line cells cannot make a part unexpectedly oversized.
    """
    full = render_table(table, table_format=table_format)
    if not full:
        return []
    if len(full) <= chunk_size or len(table.body_rows) <= 1:
        return [full]

    parts: list[str] = []
    current: list[list[str]] = []
    for row in table.body_rows:
        candidate = TableData(
            caption=table.caption,
            header_rows=table.header_rows,
            body_rows=[*current, row],
        )
        if current and len(render_table(candidate, table_format=table_format)) > chunk_size:
            parts.append(
                render_table(
                    TableData(
                        caption=table.caption,
                        header_rows=table.header_rows,
                        body_rows=current,
                    ),
                    table_format=table_format,
                )
            )
            current = [row]
        else:
            current = [*current, row]

    if current:
        parts.append(
            render_table(
                TableData(
                    caption=table.caption,
                    header_rows=table.header_rows,
                    body_rows=current,
                ),
                table_format=table_format,
            )
        )
    return parts


__all__ = ["TableData", "TableFormat", "render_table", "table_text_parts"]
