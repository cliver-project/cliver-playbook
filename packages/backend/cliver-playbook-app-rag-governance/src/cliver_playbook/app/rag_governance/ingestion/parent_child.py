"""Split a document into parent sections and short child chunks.

The small-to-big contract has two representations per section:

- **Children** are short, overlapping-ish pieces that are embedded for
  retrieval. They are the only thing a vector index ever sees.
- **Parents** are the original section bodies, kept verbatim for
  generation. An answer is grounded in the parent the source actually
  wrote, not in an LLM summary of it.

Markdown headings delimit parent sections. A section body longer than
``parent_max_chars`` is split on paragraph boundaries into parts that
share the heading path with a ``#part-N`` suffix, because an oversized
parent is both a poor generation context and a sign that the heading
level was too coarse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cliver_playbook.app.rag.chunking.base import split_text_with_offsets

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_TRAILING_HASHES = re.compile(r"[ \t]+#+[ \t]*$")
_PARAGRAPH = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True)
class ParentSection:
    """One parent body and the children split from it.

    ``section_path`` is ``H<level>#<heading text>`` for a headed
    section and ``""`` for text before the first heading. When a body
    was split, each part gets a ``#part-N`` suffix so two parts never
    share an identity.
    """

    text: str
    section_path: str
    children: list[str] = field(default_factory=list)


def split_parent_child(
    text: str,
    *,
    child_size: int = 512,
    child_overlap: int = 64,
    parent_max_chars: int = 4000,
) -> list[ParentSection]:
    """Return the document's parent sections, each with child chunks.

    Empty sections produce no parent: a heading with no body would add
    a row that retrieval can never select. Text before the first
    heading keeps an empty path, so a plain-text document with no
    headings still becomes one parent.
    """
    if child_size <= 0:
        raise ValueError("child_size must be positive")
    if child_overlap < 0 or child_overlap >= child_size:
        raise ValueError("child_overlap must be >= 0 and < child_size")
    if parent_max_chars <= 0:
        raise ValueError("parent_max_chars must be positive")

    sections: list[ParentSection] = []
    for section_path, body in _sections(text):
        parts = _paragraph_parts(body, parent_max_chars)
        for part_number, part in enumerate(parts, start=1):
            path = section_path if len(parts) == 1 else f"{section_path}#part-{part_number}"
            children = [
                piece.strip()
                for piece, _start, _end in split_text_with_offsets(
                    text=part,
                    chunk_size=child_size,
                    chunk_overlap=child_overlap,
                )
            ]
            children = [child for child in children if child]
            if children:
                sections.append(ParentSection(text=part, section_path=path, children=children))
    return sections


def _sections(text: str) -> list[tuple[str, str]]:
    """Return ``(section_path, body)`` pairs in document order."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        body = text.strip()
        return [("", body)] if body else []

    sections: list[tuple[str, str]] = []
    prefix = text[: matches[0].start()].strip()
    if prefix:
        sections.append(("", prefix))
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((_heading_path(match), body))
    return sections


def _heading_path(match: re.Match[str]) -> str:
    """``H2#B`` for ``## B``; trailing closing hashes are not part of the title."""
    level = len(match.group(1))
    title = _TRAILING_HASHES.sub("", match.group(2)).strip()
    return f"H{level}#{title}"


def _paragraph_parts(text: str, max_chars: int) -> list[str]:
    """Split ``text`` into parts of at most roughly ``max_chars``.

    Paragraph boundaries are preferred. A single paragraph over the
    limit is split by the recursive splitter so the invariant holds
    even for a wall of text with no blank lines.
    """
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    current_length = 0

    for paragraph in (piece.strip() for piece in _PARAGRAPH.split(text)):
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                parts.append("\n\n".join(current))
                current = []
                current_length = 0
            for piece, _start, _end in split_text_with_offsets(
                text=paragraph,
                chunk_size=max_chars,
                chunk_overlap=0,
            ):
                if piece.strip():
                    parts.append(piece.strip())
            continue

        addition = len(paragraph) + (2 if current else 0)
        if current and current_length + addition > max_chars:
            parts.append("\n\n".join(current))
            current = [paragraph]
            current_length = len(paragraph)
        else:
            current.append(paragraph)
            current_length += addition

    if current:
        parts.append("\n\n".join(current))
    return parts or [text]
