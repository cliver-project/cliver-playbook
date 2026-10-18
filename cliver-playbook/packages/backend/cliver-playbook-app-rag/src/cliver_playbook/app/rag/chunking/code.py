"""Code-aware chunker: langchain's language-aware recursive splitter.

For source code, the recursive splitter's "natural" separator
preferences (``\\n\\n``, ``\\n``, `` ``) become unhelpful — splitting
on a blank line is the natural function boundary, but the recursive
character splitter does not know that. LangChain's
``from_language`` mode ships language-specific grammars that split
on function / class / method boundaries; for Python, JS, TS, Go,
Java, Rust, C++, C#, Ruby, PHP, this is the same AST-aware splitting
described in the design doc's research notes (tree-sitter under the
hood in newer versions).
"""

from __future__ import annotations

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from cliver_playbook.app.rag.chunking.base import (
    Chunk,
    Document,
    SourceOffset,
    make_chunk_id,
)

VERSION = "1.0.0"

_MIME_TO_LANGUAGE: dict[str, Language] = {
    "text/x-python": Language.PYTHON,
    "text/x-javascript": Language.JS,
    "text/x-typescript": Language.TS,
    "text/x-go": Language.GO,
    "text/x-java": Language.JAVA,
    "text/x-rust": Language.RUST,
    "text/x-c++": Language.CPP,
    "text/x-csharp": Language.CSHARP,
    "text/x-ruby": Language.RUBY,
    "text/x-php": Language.PHP,
}


def _detect_language(mime_type: str) -> Language | None:
    return _MIME_TO_LANGUAGE.get(mime_type)


class CodeChunker:
    """Code-aware chunker.

    The splitter defaults to Python when the mime type is unknown;
    callers should pass ``mime_type="text/x-python"`` /
    ``"text/x-typescript"`` / etc. so the right grammar is picked.
    When the mime type does not map to a known language, the
    splitter falls back to Python grammar; this is documented, not
    silent, because the mime type is part of the Document model.
    """

    name = "code"
    version = VERSION

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> list[Chunk]:
        text = doc.raw if isinstance(doc.raw, str) else doc.raw.decode("utf-8")
        language = _detect_language(doc.mime_type) or Language.PYTHON
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=language,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        texts = splitter.split_text(text)
        chunks: list[Chunk] = []
        for ordinal, t in enumerate(texts):
            chunks.append(
                Chunk(
                    id=make_chunk_id(doc.id, doc.source_version, ordinal, t),
                    text=t,
                    metadata={
                        **dict(doc.metadata),
                        "language": language.value,
                    },
                    parent_id=None,
                    source_offset=SourceOffset(start=0, end=len(t), unit="char"),
                )
            )
        return chunks
