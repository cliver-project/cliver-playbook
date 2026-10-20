"""Tests for the chunker option contract and the catalog descriptors."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from cliver_playbook.app.rag.chunking.base import (
    Chunk,
    chunk_text_recursive,
    split_text_with_offsets,
)
from cliver_playbook.app.rag.chunking.options import (
    BaseOptions,
    DocxOptions,
    EmptyOptions,
    HtmlOptions,
    describe_options,
)


def test_empty_options_have_no_fields() -> None:
    assert describe_options(EmptyOptions) == []


def test_docx_options_describe_flat_fields() -> None:
    fields = {field["name"]: field for field in describe_options(DocxOptions)}

    assert fields["heading_based"]["type"] == "boolean"
    assert fields["heading_based"]["default"] is True
    assert fields["max_heading_level"]["type"] == "integer"
    assert fields["max_heading_level"]["minimum"] == 1
    assert fields["max_heading_level"]["maximum"] == 9
    assert fields["max_heading_level"]["default"] == 6
    assert fields["table_format"]["type"] == "enum"
    assert fields["table_format"]["enum"] == ["markdown", "html"]
    assert fields["table_format"]["default"] == "markdown"
    assert fields["drop_toc"]["type"] == "boolean"
    assert fields["drop_toc"]["default"] is True


def test_html_options_describe_optional_strings() -> None:
    fields = {field["name"]: field for field in describe_options(HtmlOptions)}

    assert fields["content_selector"]["type"] == "string"
    assert fields["content_selector"]["default"] is None
    assert fields["remove_selectors"]["type"] == "string"
    assert fields["remove_boilerplate"]["type"] == "boolean"
    assert fields["include_links"]["type"] == "boolean"


def test_unknown_option_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DocxOptions.model_validate({"remove_boilerplte": True})


def test_required_option_is_rejected_by_describe() -> None:
    class Required(BaseOptions):
        value: str

    with pytest.raises(TypeError, match="default"):
        describe_options(Required)


def test_nested_option_is_rejected_by_describe() -> None:
    class Child(BaseModel):
        value: str = "x"

    class Nested(BaseOptions):
        child: Child = Child()

    with pytest.raises(TypeError, match="flat primitive"):
        describe_options(Nested)


def test_offset_splitter_returns_exact_slices_without_overlap() -> None:
    text = "Sentence one. Sentence two. " * 20
    pieces = split_text_with_offsets(text=text, chunk_size=80, chunk_overlap=0)

    assert pieces
    cursor = 0
    for piece, start, end in pieces:
        assert start >= cursor
        assert text[start:end] == piece
        cursor = end


def test_offset_splitter_keeps_offsets_monotonic_with_overlap() -> None:
    text = "Sentence one. Sentence two. " * 20
    pieces = split_text_with_offsets(text=text, chunk_size=80, chunk_overlap=10)

    cursor = 0
    for _piece, start, end in pieces:
        assert start >= cursor
        assert end >= start
        cursor = end


def test_chunk_text_recursive_keeps_offsets_and_ids() -> None:
    text = "alpha beta gamma. " * 30
    chunks = chunk_text_recursive(
        text=text,
        document_id="d",
        source_version="v1",
        chunk_size=100,
        chunk_overlap=0,
        metadata={},
    )
    repeat = chunk_text_recursive(
        text=text,
        document_id="d",
        source_version="v1",
        chunk_size=100,
        chunk_overlap=0,
        metadata={},
    )

    assert chunks
    assert all(
        text[chunk.source_offset.start : chunk.source_offset.end] == chunk.text for chunk in chunks
    )
    assert [chunk.id for chunk in chunks] == [chunk.id for chunk in repeat]
    assert all(isinstance(chunk, Chunk) for chunk in chunks)
