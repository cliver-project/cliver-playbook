"""Parent/child splitting: headings, pre-heading text, oversized sections."""

from __future__ import annotations

from cliver_playbook.app.rag_governance.ingestion.parent_child import (
    split_parent_child,
    split_parsed_blocks,
)
from cliver_playbook.app.rag_governance.stages.base import ParsedBlock


def test_markdown_headings_become_separate_parents() -> None:
    text = "# A\nalpha\n\n## B\nbeta\n"

    sections = split_parent_child(text, child_size=32, child_overlap=0)

    assert [section.section_path for section in sections] == ["H1#A", "H2#B"]
    assert sections[0].children == ["alpha"]
    assert sections[1].children == ["beta"]


def test_text_before_the_first_heading_is_its_own_parent() -> None:
    sections = split_parent_child(
        "intro paragraph\n\n# A\nalpha\n",
        child_size=64,
        child_overlap=0,
    )

    assert [section.section_path for section in sections] == ["", "H1#A"]
    assert sections[0].text == "intro paragraph"


def test_plain_text_without_headings_is_one_parent() -> None:
    sections = split_parent_child("just some text\n", child_size=64, child_overlap=0)

    assert len(sections) == 1
    assert sections[0].section_path == ""
    assert sections[0].children == ["just some text"]


def test_empty_headings_produce_no_parent() -> None:
    sections = split_parent_child("# A\n\n## B\nbeta\n", child_size=32, child_overlap=0)

    assert [section.section_path for section in sections] == ["H2#B"]


def test_long_parent_is_split_with_part_suffixes() -> None:
    paragraphs = ["甲" * 40 for _ in range(4)]
    text = "# A\n" + "\n\n".join(paragraphs) + "\n"

    sections = split_parent_child(
        text,
        child_size=32,
        child_overlap=0,
        parent_max_chars=90,
    )

    assert [section.section_path for section in sections] == [
        "H1#A#part-1",
        "H1#A#part-2",
    ]
    assert all(section.text for section in sections)


def test_children_are_short_and_overlap_is_honoured() -> None:
    body = " ".join(f"word{i}" for i in range(40))
    sections = split_parent_child(f"# A\n{body}\n", child_size=40, child_overlap=10)

    assert len(sections) == 1
    assert len(sections[0].children) > 1
    assert all(len(child) <= 40 for child in sections[0].children)


def test_parsed_blocks_keep_the_full_structure_path_and_page_locator() -> None:
    blocks = [
        ParsedBlock(kind="heading", text="Chapter", level=1),
        ParsedBlock(kind="heading", text="第十二条", level=2),
        ParsedBlock(kind="text", text="Body one", locator={"page": 3}),
        ParsedBlock(kind="page_break", locator={"page": 4}),
        ParsedBlock(kind="text", text="Body two", locator={"page": 4}),
    ]

    sections = split_parsed_blocks(blocks, child_size=32, child_overlap=0)

    assert [section.text for section in sections] == ["Body one", "Body two"]
    assert all(section.section_path == "H2#第十二条" for section in sections)
    assert sections[0].structure_path == [
        {"type": "heading", "level": 1, "title": "Chapter", "ordinal": 0},
        {"type": "heading", "level": 2, "title": "第十二条", "ordinal": 1},
    ]
    assert sections[0].locator == {
        "clause": "第十二条",
        "page_start": 3,
        "page_end": 3,
    }
    assert sections[1].locator == {
        "clause": "第十二条",
        "page_start": 4,
        "page_end": 4,
    }


def test_parsed_blocks_mark_oversized_parts_in_the_structure_path() -> None:
    paragraphs = ["甲" * 40 for _ in range(4)]
    blocks = [ParsedBlock(kind="heading", text="A", level=1)] + [
        ParsedBlock(kind="text", text=paragraph) for paragraph in paragraphs
    ]

    sections = split_parsed_blocks(
        blocks,
        child_size=32,
        child_overlap=0,
        parent_max_chars=90,
    )

    assert [section.section_path for section in sections] == [
        "H1#A#part-1",
        "H1#A#part-2",
    ]
    assert [section.structure_path[-1] for section in sections] == [
        {"type": "part", "ordinal": 1},
        {"type": "part", "ordinal": 2},
    ]
