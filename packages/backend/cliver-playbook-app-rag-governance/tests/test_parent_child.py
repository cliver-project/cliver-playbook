"""Parent/child splitting: headings, pre-heading text, oversized sections."""

from __future__ import annotations

from cliver_playbook.app.rag_governance.ingestion.parent_child import split_parent_child


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
