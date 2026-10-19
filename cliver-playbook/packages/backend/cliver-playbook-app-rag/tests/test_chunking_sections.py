"""Tests for heading-aware section assembly and chunk emission."""

from __future__ import annotations

from cliver_playbook.app.rag.chunking.sections import (
    build_sections,
    chunk_sections,
    heading_block,
    table_block,
    text_block,
)
from cliver_playbook.app.rag.chunking.tables import TableData


def _paths(sections: list) -> list[list[str]]:
    return [
        [f"H{heading.level}#{heading.text}" for heading in section.heading_path]
        for section in sections
    ]


def test_heading_stack_builds_and_pops_paths() -> None:
    sections = build_sections(
        [
            heading_block(1, "Policy"),
            text_block("intro"),
            heading_block(2, "Scope"),
            text_block("scope body"),
            heading_block(2, "Roles"),
            text_block("roles body"),
            heading_block(3, "Deep"),
            text_block("deep body"),
            heading_block(2, "Back"),
            text_block("back body"),
        ]
    )

    assert _paths(sections) == [
        ["H1#Policy"],
        ["H1#Policy", "H2#Scope"],
        ["H1#Policy", "H2#Roles"],
        ["H1#Policy", "H2#Roles", "H3#Deep"],
        ["H1#Policy", "H2#Back"],
    ]


def test_content_before_first_heading_has_empty_path() -> None:
    sections = build_sections([text_block("preamble"), heading_block(1, "A"), text_block("a")])

    assert _paths(sections) == [[], ["H1#A"]]


def test_consecutive_headings_do_not_create_empty_sections() -> None:
    sections = build_sections([heading_block(1, "A"), heading_block(2, "B"), text_block("body")])

    assert _paths(sections) == [["H1#A", "H2#B"]]


def test_disabling_heading_sections_keeps_heading_as_text() -> None:
    sections = build_sections(
        [heading_block(1, "A"), text_block("body")],
        heading_based=False,
    )

    assert _paths(sections) == [[]]
    assert [block.text for block in sections[0].blocks] == ["A", "body"]


def test_deep_heading_becomes_body_text() -> None:
    sections = build_sections(
        [heading_block(1, "A"), heading_block(4, "Too deep"), text_block("body")],
        max_heading_level=3,
    )

    assert _paths(sections) == [["H1#A"]]
    assert [block.text for block in sections[0].blocks] == ["Too deep", "body"]


def test_chunk_sections_sets_metadata_and_prefix() -> None:
    sections = build_sections(
        [heading_block(1, "Policy"), heading_block(2, "Scope"), text_block("body")]
    )

    chunks = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={"source": "docx"},
        chunk_size=512,
        chunk_overlap=0,
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["section_path"] == ["H1#Policy", "H2#Scope"]
    assert chunks[0].metadata["source"] == "docx"
    assert chunks[0].text == "Policy > Scope\n\nbody"
    assert chunks[0].source_offset.start == 0
    assert chunks[0].source_offset.end == len("body")


def test_chunk_sections_can_omit_heading_prefix() -> None:
    sections = build_sections([heading_block(1, "Policy"), text_block("body")])

    chunks = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={},
        chunk_size=512,
        chunk_overlap=0,
        include_heading_path=False,
    )

    assert chunks[0].text == "body"
    assert chunks[0].metadata["section_path"] == ["H1#Policy"]


def test_oversized_section_offsets_are_relative_to_the_body() -> None:
    body = "alpha beta gamma. " * 20
    sections = build_sections([heading_block(1, "Policy"), text_block(body)])

    chunks = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={},
        chunk_size=80,
        chunk_overlap=0,
        include_heading_path=True,
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith("Policy\n\n")
        piece = chunk.text.removeprefix("Policy\n\n")
        assert body[chunk.source_offset.start : chunk.source_offset.end] == piece
    assert [chunk.source_offset.start for chunk in chunks] == sorted(
        chunk.source_offset.start for chunk in chunks
    )


def test_ordinals_are_global_across_sections() -> None:
    sections = build_sections(
        [heading_block(1, "A"), text_block("a"), heading_block(1, "B"), text_block("b")]
    )

    chunks = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={},
        chunk_size=512,
        chunk_overlap=0,
    )

    assert len(chunks) == 2
    assert len({chunk.id for chunk in chunks}) == 2


def test_tables_can_be_included_in_markdown_or_html() -> None:
    table = TableData(header_rows=[["name"]], body_rows=[["alpha"]])
    sections = build_sections([heading_block(1, "A"), table_block(table)])

    markdown = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={},
        chunk_size=512,
        chunk_overlap=0,
        include_heading_path=False,
    )
    html = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={},
        chunk_size=512,
        chunk_overlap=0,
        include_heading_path=False,
        table_format="html",
    )

    assert "| name |" in markdown[0].text
    assert "<table>" in html[0].text


def test_tables_can_be_excluded() -> None:
    table = TableData(header_rows=[["name"]], body_rows=[["alpha"]])
    sections = build_sections([heading_block(1, "A"), table_block(table)])

    chunks = chunk_sections(
        sections,
        document_id="d",
        source_version="v1",
        metadata={},
        chunk_size=512,
        chunk_overlap=0,
        include_tables=False,
    )

    assert chunks == []
