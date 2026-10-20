"""Tests for the HTML chunker."""

from __future__ import annotations

import pytest

from cliver_playbook.app.rag.chunking import Document, get_chunker
from cliver_playbook.app.rag.chunking.base import ChunkerOptionError, EmptyDocumentError
from cliver_playbook.app.rag.chunking.options import HtmlOptions

PAGE = """
<html lang="en">
  <head><title>Policy doc</title><style>.x { color: red; }</style></head>
  <body>
    <nav><a href="/home">Home</a></nav>
    <header>Site header</header>
    <main>
      <h1>Policy</h1>
      <p>intro</p>
      <h2>Scope</h2>
      <p>scope <a href="/x">details</a></p>
      <table>
        <caption>Data</caption>
        <thead><tr><th>name</th><th>value</th></tr></thead>
        <tbody><tr><td>alpha</td><td>1</td></tr></tbody>
      </table>
    </main>
    <aside>Related</aside>
    <footer>Footer</footer>
  </body>
</html>
"""


def _split(html: str | bytes, **kwargs):
    doc = Document(id="html-1", source_version="v1", mime_type="text/html", raw=html)
    return get_chunker("html").split(doc, **kwargs)


def _texts(chunks) -> str:
    return "\n".join(chunk.text for chunk in chunks)


def test_structure_metadata_and_default_boilerplate_removal() -> None:
    chunks = _split(PAGE, chunk_size=512, chunk_overlap=0)
    text = _texts(chunks)

    assert chunks[0].metadata["html_title"] == "Policy doc"
    assert chunks[0].metadata["language"] == "en"
    assert [chunk.metadata["section_path"] for chunk in chunks] == [
        ["H1#Policy"],
        ["H1#Policy", "H2#Scope"],
    ]
    assert "Home" not in text
    assert "Site header" not in text
    assert "Related" not in text
    assert "Footer" not in text
    assert "[details](/x)" in text
    assert "| name | value |" in text
    assert "| alpha | 1 |" in text


def test_boilerplate_removal_can_be_disabled() -> None:
    chunks = _split(
        PAGE,
        chunk_size=512,
        chunk_overlap=0,
        options=HtmlOptions(remove_boilerplate=False),
    )

    assert "Home" in _texts(chunks)


def test_content_selector_limits_the_root() -> None:
    chunks = _split(
        PAGE,
        chunk_size=512,
        chunk_overlap=0,
        options=HtmlOptions(content_selector="main", remove_boilerplate=False),
    )
    text = _texts(chunks)

    assert "Policy" in text
    assert "Home" not in text
    assert "Footer" not in text


def test_content_selector_with_no_match_is_empty() -> None:
    with pytest.raises(EmptyDocumentError, match="matched no element"):
        _split(PAGE, options=HtmlOptions(content_selector="#missing"))


def test_invalid_selector_is_an_option_error() -> None:
    with pytest.raises(ChunkerOptionError, match="content selector"):
        _split(PAGE, options=HtmlOptions(content_selector="div["))

    with pytest.raises(ChunkerOptionError, match="remove selector"):
        _split(PAGE, options=HtmlOptions(remove_selectors="div["))


def test_remove_selectors_runs_inside_the_root() -> None:
    chunks = _split(
        PAGE,
        chunk_size=512,
        chunk_overlap=0,
        options=HtmlOptions(remove_selectors="table, h2"),
    )

    text = _texts(chunks)
    assert "| name |" not in text
    assert "Scope" not in text
    assert "intro" in text
    assert "scope" in text


def test_links_can_be_disabled() -> None:
    chunks = _split(
        PAGE,
        chunk_size=512,
        chunk_overlap=0,
        options=HtmlOptions(include_links=False),
    )

    assert "details" in _texts(chunks)
    assert "(/x)" not in _texts(chunks)


def test_nested_lists_do_not_duplicate_text() -> None:
    html = "<ul><li>one<ul><li>two</li></ul></li><li>three</li></ul>"

    text = _texts(_split(html, chunk_size=512, chunk_overlap=0))

    assert text.count("one") == 1
    assert text.count("two") == 1
    assert text.count("three") == 1


def test_container_direct_text_and_paragraphs_both_survive() -> None:
    html = "<div>Hello <b>world</b><p>paragraph</p></div>"

    text = _texts(_split(html, chunk_size=512, chunk_overlap=0))

    assert "Hello world" in text
    assert "paragraph" in text


def test_bytes_are_decoded_from_the_declared_charset() -> None:
    raw = ('<html><head><meta charset="gbk"></head><body><p>你好世界</p></body></html>').encode(
        "gbk"
    )

    assert "你好世界" in _texts(_split(raw, chunk_size=512, chunk_overlap=0))


def test_heading_based_can_be_disabled() -> None:
    html = "<h1>Policy</h1><p>body</p>"

    chunks = _split(
        html,
        chunk_size=512,
        chunk_overlap=0,
        options=HtmlOptions(heading_based=False),
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Policy\n\nbody"
    assert chunks[0].metadata["section_path"] == []


def test_tables_can_be_excluded_or_rendered_as_html() -> None:
    html = "<table><tr><th>name</th></tr><tr><td>alpha</td></tr></table>"

    with pytest.raises(EmptyDocumentError):
        _split(html, options=HtmlOptions(include_tables=False))

    as_html = _split(
        html,
        chunk_size=512,
        chunk_overlap=0,
        options=HtmlOptions(table_format="html"),
    )
    assert "<table>" in as_html[0].text
    assert "<td>alpha</td>" in as_html[0].text


def test_empty_after_removal_is_rejected() -> None:
    with pytest.raises(EmptyDocumentError):
        _split("<html><body><script>only()</script></body></html>")
