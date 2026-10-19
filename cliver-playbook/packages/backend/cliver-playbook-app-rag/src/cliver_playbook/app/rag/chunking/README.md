# Reusable chunking subpackage

This folder is a self-contained chunking toolkit. It has no imports from the
rest of `cliver_playbook`: every internal import is relative and third-party
parsers are imported lazily inside `split`. You can copy the folder into
another Python project, or import it from this package, without wiring up the
RAG database, HTTP layer, or stage registry.

## What is in the folder

| File | Purpose |
| --- | --- |
| `base.py` | `Document`, `Chunk`, `SourceOffset`, the `Chunker` protocol, error types, content-hash IDs, and the recursive splitter with character offsets |
| `options.py` | Flat Pydantic option models and `describe_options` for UI descriptors |
| `sections.py` | Heading-aware section assembly shared by the structured chunkers |
| `tables.py` | Table rendering as Markdown or HTML, including row-safe splitting of oversized tables |
| `recursive.py` | Default plain-text chunker |
| `markdown.py` | Markdown-aware chunker |
| `code.py` | Code-aware chunker |
| `pdf.py` | PDF chunker (layout text, no OCR) |
| `docx.py` | Word `.docx` chunker |
| `html.py` | HTML chunker |
| `registry.py` | Name-to-factory registry used by the RAG stages |

## Dependencies

Required for every chunker:

- `pydantic`
- `langchain-text-splitters`

Only when the corresponding chunker is used:

- `python-docx>=1.2,<2` for `docx`
- `beautifulsoup4>=4.12` for `html` (the stdlib `html.parser` is enough)
- `unstructured[pdf]>=0.16` for `pdf`

The lazy imports mean a project that only copies `recursive.py` does not need
the Word or HTML parser installed.

## Usage

```python
from pathlib import Path

from chunking import Document, DocxOptions, get_chunker

document = Document(
    id="policy-v1",
    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    raw=Path("policy.docx").read_bytes(),
)
chunks = get_chunker("docx").split(
    document,
    chunk_size=512,
    chunk_overlap=64,
    options=DocxOptions(drop_toc=True, include_heading_path=True),
)
for chunk in chunks:
    print(chunk.metadata["section_path"], chunk.source_offset, chunk.text[:80])
```

`split` also accepts a plain mapping for `options`, so a caller that already
has JSON can pass `{"drop_toc": False}`.

If you copy the folder into another project, keep it as a package (it has
`__init__.py`) and import it under whatever name you gave it, for example
`my_project.chunking`. The relative imports continue to work.

## The chunker contract

```python
class Chunker(Protocol):
    name: str
    version: str
    options_model: type[BaseModel]

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        options: OptionsInput | None = None,
    ) -> list[Chunk]: ...
```

- `version` is the implementation version. It is recorded with the output so
  a later change in chunking behavior can be detected.
- `options_model` is the single source of truth for configurable behavior.
  Chunkers with fixed output use `EmptyOptions`.
- `split` raises `EmptyDocumentError` when the input has no extractable text,
  `ChunkerInputError` when the bytes are the wrong format, and
  `ChunkerOptionError` when an option is syntactically valid but unusable
  (for example, invalid CSS).

## Options

`SectionOptions` is shared by `docx` and `html`:

| Option | Type / default | Effect |
| --- | --- | --- |
| `heading_based` | bool, `True` | Group blocks into heading-delimited sections. `False` emits one section; heading text becomes body text. |
| `max_heading_level` | int 1-9, `6` | Headings deeper than this level are treated as body text. |
| `include_tables` | bool, `True` | Include table content. `False` omits tables entirely. |
| `table_format` | `markdown` or `html`, `markdown` | How tables are rendered into chunk text. |
| `include_heading_path` | bool, `True` | Prefix each chunk with `" > ".join(heading texts)` and a blank line. The path is always present in `metadata["section_path"]`. |

`DocxOptions` adds:

| Option | Type / default | Effect |
| --- | --- | --- |
| `drop_toc` | bool, `True` | Skip paragraphs whose style name or id starts with `TOC`. |

`HtmlOptions` adds:

| Option | Type / default | Effect |
| --- | --- | --- |
| `content_selector` | string / `None` | CSS selector for the content root. Empty means the whole body. No match raises `EmptyDocumentError`. |
| `remove_selectors` | string / `None` | Comma-separated CSS selectors removed after the root is chosen. Invalid syntax raises `ChunkerOptionError`. |
| `remove_boilerplate` | bool, `True` | Remove navigation, headers, footers, sidebars, forms, interactive controls, landmark roles, and `aria-hidden="true"` elements. |
| `include_links` | bool, `True` | Render inline anchors as `[text](href)`. `False` keeps only the text. Links are never fetched. |

Every option has a default, and `extra="forbid"` turns a misspelled option
into a validation error rather than a silent no-op. `describe_options`
converts a model into flat UI descriptors and rejects nested models, arrays,
required fields, and unsupported types.

## Section and offset semantics

- Blocks before the first heading form a section with an empty heading path.
- A heading closes the previous section; sibling headings do not inherit the
  previous sibling's children.
- Consecutive headings with no body produce no empty section.
- A section body that fits `chunk_size` becomes one chunk; a larger body is
  split with the same recursive splitter as the default chunker.
- `chunk_overlap` applies inside a section body, never across section
  boundaries.
- `metadata["section_path"]` uses the Markdown chunker's convention, for
  example `["H1#Policy", "H2#Scope"]`.
- `source_offset` is relative to the section body, not to the whole document.
  This matches the Markdown chunker; the parsers cannot provide global
  character offsets reliably after layout normalization.
- Chunk IDs are content hashes of document id, source version, ordinal, and
  text. Changing options changes the text and therefore the IDs, which is the
  intended behavior for a re-chunk.

## Limitations

- Legacy Word `.doc` (OLE/CFB) is rejected with a message asking for `.docx`.
  Encrypted OOXML packages are rejected the same way.
- DOCX reading covers the main document body only. Headers, footers,
  footnotes, comments, and text boxes are excluded. Vertically or horizontally
  merged cells repeat their text through `row.cells`, preserving column
  alignment.
- HTML `colspan` and `rowspan` are not expanded. Images and their alt text are
  ignored. A table nested in a table contributes its text to the outer cell.
- PDF extraction is text-only; scanned pages need OCR before chunking.
- A heading-path prefix is added to the chunk text after sizing, so a chunk
  body can exceed `chunk_size` by the length of the prefix. The path is
  bounded by heading depth and is normally much smaller than the body.
