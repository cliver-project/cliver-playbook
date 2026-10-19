"""HTML chunker.

Parses HTML with BeautifulSoup's stdlib ``html.parser`` builder and
walks the DOM in document order, emitting heading, text, and table
blocks for the shared section/table helpers. No network access: links
are rendered as text (optionally as ``[text](href)``) and never
resolved.

The walk deliberately avoids two common sources of duplicate or lost
text:

* a container's direct inline text (text nodes, ``<b>``, ``<span>``,
  ...) is emitted once, while nested block elements are walked
  separately;
* a text block emits its inline text excluding nested blocks, then
  descends only into nested block children (``<li><ul>``,
  ``<blockquote><p>``, ...).

By default navigation, headers, footers, sidebars, forms, and
landmark-role elements are removed. ``content_selector`` is applied
before the boilerplate pass, so selecting ``main`` still works when
the page wraps it in a boilerplate ``<div>``. ``remove_selectors``
runs last, inside the chosen root.

Known limitations: ``colspan``/``rowspan`` are not expanded, images
and their alt text are ignored, and a table nested inside a table
contributes its text to the outer cell.
"""

from __future__ import annotations

import re

from .base import (
    Chunk,
    ChunkerInputError,
    ChunkerOptionError,
    Document,
    EmptyDocumentError,
    OptionsInput,
)
from .options import HtmlOptions
from .sections import (
    Block,
    build_sections,
    chunk_sections,
    heading_block,
    table_block,
    text_block,
)
from .tables import TableData

VERSION = "1.0.0"

_HEADING_TAGS = {f"h{level}" for level in range(1, 7)}
_TEXT_BLOCK_TAGS = {"p", "li", "blockquote", "dt", "dd", "figcaption", "pre"}
_CONTAINER_TAGS = {
    "address",
    "article",
    "aside",
    "body",
    "div",
    "dl",
    "fieldset",
    "figure",
    "footer",
    "form",
    "header",
    "html",
    "main",
    "nav",
    "ol",
    "section",
    "ul",
}
_BLOCK_NAMES = _HEADING_TAGS | _TEXT_BLOCK_TAGS | _CONTAINER_TAGS | {"table"}

_DISCARD_TAGS = (
    "head",
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "object",
    "embed",
)

_BOILERPLATE_TAGS = (
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "input",
    "select",
    "textarea",
)
_BOILERPLATE_SELECTORS = (
    "[role=navigation]",
    "[role=banner]",
    "[role=contentinfo]",
    "[role=search]",
    '[aria-hidden="true"]',
)

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _coerce_options(options: OptionsInput | None) -> HtmlOptions:
    if options is None:
        return HtmlOptions()
    if isinstance(options, HtmlOptions):
        return options
    return HtmlOptions.model_validate(options)


def _decompose(tag) -> None:
    # A parent removal already detaches its children; calling
    # decompose() on one of those children is unnecessary and, for
    # some bs4 versions, unsafe.
    if tag.parent is not None:
        tag.decompose()


def _is_relative_javascript(href: str) -> bool:
    return href.startswith("#") or href.lower().startswith("javascript:")


def _collect_inline(node, parts: list[str], *, links: bool, preserve: bool) -> None:
    for child in node.children:
        if isinstance(child, str):
            parts.append(str(child))
            continue

        name = getattr(child, "name", None)
        if name == "br":
            parts.append("\n")
        elif name == "a":
            text = _inline_text(child, links=False, preserve=False)
            href = (child.get("href") or "").strip()
            if links and href and not _is_relative_javascript(href) and text:
                parts.append(f"[{text}]({href})")
            else:
                parts.append(text)
        elif name in _BLOCK_NAMES:
            # Nested blocks are emitted by the block walker, never as
            # part of this inline run.
            continue
        else:
            _collect_inline(child, parts, links=links, preserve=preserve)


def _inline_text(node, *, links: bool, preserve: bool = False) -> str:
    parts: list[str] = []
    _collect_inline(node, parts, links=links, preserve=preserve)
    text = "".join(parts)
    return text.strip("\n") if preserve else _normalize(text)


def _cell_text(cell) -> str:
    # Cells often contain paragraphs; flatten everything inside the
    # cell. Nested tables are flattened too (documented limitation).
    return _normalize(cell.get_text(" ", strip=True))


def _row_cells(row) -> list[str]:
    return [_cell_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]


def _table_data(table) -> TableData:
    caption_tag = table.find("caption")
    caption = _normalize(caption_tag.get_text(" ", strip=True)) if caption_tag else ""

    thead = table.find("thead")
    header_rows: list[list[str]] = []
    body_rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = _row_cells(row)
        if not cells:
            continue
        in_thead = row.find_parent("thead") is not None
        implicit_header = (
            thead is None and not header_rows and bool(row.find_all("th", recursive=False))
        )
        if in_thead or implicit_header:
            header_rows.append(cells)
        else:
            body_rows.append(cells)

    return TableData(caption=caption, header_rows=header_rows, body_rows=body_rows)


def _handle_container(container, blocks: list[Block], options: HtmlOptions) -> None:
    direct = _inline_text(container, links=options.include_links)
    if direct:
        blocks.append(text_block(direct))
    for child in container.children:
        name = getattr(child, "name", None)
        if name in _BLOCK_NAMES:
            _handle_block(child, blocks, options)


def _handle_nested_blocks(element, blocks: list[Block], options: HtmlOptions) -> None:
    for child in element.children:
        name = getattr(child, "name", None)
        if name in _BLOCK_NAMES:
            _handle_block(child, blocks, options)


def _handle_block(element, blocks: list[Block], options: HtmlOptions) -> None:
    name = element.name
    if name == "table":
        data = _table_data(element)
        if data.header_rows or data.body_rows or data.caption:
            blocks.append(table_block(data))
        return

    if name in _HEADING_TAGS:
        text = _inline_text(element, links=False)
        if text:
            blocks.append(heading_block(int(name[1]), text))
        return

    if name in _TEXT_BLOCK_TAGS:
        text = _inline_text(element, links=options.include_links, preserve=name == "pre")
        if text:
            blocks.append(text_block(text))
        _handle_nested_blocks(element, blocks, options)
        return

    # Any other block name is a container: emit its own inline text,
    # then walk its block children in document order.
    _handle_container(element, blocks, options)


def _select(root, selector: str, *, what: str) -> list:
    try:
        return root.select(selector)
    except Exception as exc:
        # soupsieve's SelectorSyntaxError subclasses Exception directly
        # (not ValueError), so a targeted except clause would miss it.
        raise ChunkerOptionError(f"invalid {what} {selector!r}: {exc}") from exc


def _choose_root(soup, options: HtmlOptions):
    selector = (options.content_selector or "").strip()
    if not selector:
        return soup
    matches = _select(soup, selector, what="content selector")
    if not matches:
        raise EmptyDocumentError("HTML content selector matched no element")
    return matches[0]


def _remove_boilerplate(root) -> None:
    for tag in root.find_all(_BOILERPLATE_TAGS):
        _decompose(tag)
    for selector in _BOILERPLATE_SELECTORS:
        for tag in root.select(selector):
            _decompose(tag)


def _remove_selectors(root, options: HtmlOptions) -> None:
    for selector in (options.remove_selectors or "").split(","):
        selector = selector.strip()
        if not selector:
            continue
        matches = _select(root, selector, what="remove selector")
        for tag in matches:
            _decompose(tag)


class HtmlChunker:
    """HTML chunker with heading-aware sections and boilerplate removal."""

    name = "html"
    version = VERSION
    options_model = HtmlOptions

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        options: OptionsInput | None = None,
    ) -> list[Chunk]:
        if not isinstance(doc.raw, (str, bytes)):
            raise ChunkerInputError("HTML input must be text or bytes")

        parsed = _coerce_options(options)

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(doc.raw, "html.parser")

        metadata = dict(doc.metadata)
        title_tag = soup.find("title")
        if title_tag is not None:
            title = _normalize(title_tag.get_text(" ", strip=True))
            if title:
                metadata.setdefault("html_title", title)
        html_tag = soup.find("html")
        if html_tag is not None and html_tag.get("lang"):
            metadata.setdefault("language", str(html_tag.get("lang")))

        for tag in soup.find_all(_DISCARD_TAGS):
            _decompose(tag)

        root = _choose_root(soup, parsed)
        if parsed.remove_boilerplate:
            _remove_boilerplate(root)
        _remove_selectors(root, parsed)

        blocks: list[Block] = []
        if getattr(root, "name", None) in (_HEADING_TAGS | _TEXT_BLOCK_TAGS | {"table"}):
            _handle_block(root, blocks, parsed)
        else:
            _handle_container(root, blocks, parsed)

        if not blocks:
            raise EmptyDocumentError("HTML produced no extractable text")

        sections = build_sections(
            blocks,
            heading_based=parsed.heading_based,
            max_heading_level=parsed.max_heading_level,
        )
        chunks = chunk_sections(
            sections,
            document_id=doc.id,
            source_version=doc.source_version,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            table_format=parsed.table_format,
            include_tables=parsed.include_tables,
            include_heading_path=parsed.include_heading_path,
        )
        if not chunks:
            raise EmptyDocumentError("HTML produced no extractable text")
        return chunks


__all__ = ["HtmlChunker"]
