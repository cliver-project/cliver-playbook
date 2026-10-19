# Reusable chunking subpackage

This folder is a self-contained chunking toolkit. Every internal import is
relative and third-party parsers are imported lazily inside `split`, so the
folder can be copied into another project or imported from this package
without the RAG database, HTTP layer, or stage registry.

## Contents

| File | Purpose |
| --- | --- |
| `base.py` | `Document`, `Chunk`, `SourceOffset`, the `Chunker` protocol, error types, content-hash IDs, and the recursive splitter with character offsets |
| `options.py` | Flat Pydantic option models and `describe_options` for UI descriptors |
| `sections.py` | Heading-aware section assembly shared by the structured chunkers |
| `tables.py` | Markdown/HTML table rendering and row-safe splitting of oversized tables |
| `recursive.py`, `markdown.py`, `code.py`, `pdf.py`, `docx.py`, `html.py` | Chunker implementations |
| `registry.py` | Name-to-factory registry used by the RAG stages |

## Dependencies

Always: `pydantic`, `langchain-text-splitters`.

Only when the corresponding chunker is used: `python-docx>=1.2,<2` for
`docx`, `beautifulsoup4>=4.12` for `html` (stdlib `html.parser`), and
`unstructured[pdf]>=0.16` for `pdf`.

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

`options` also accepts a plain mapping. When copying the folder, keep it as a
package (it has `__init__.py`) and import it under the name you gave it; the
relative imports keep working.

## Contract

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

`version` is the implementation version, recorded with the output so a later
behavior change is detectable. `options_model` is the single source of truth
for configurable behavior; fixed-output chunkers use `EmptyOptions`. `split`
raises `EmptyDocumentError` when there is no extractable text,
`ChunkerInputError` for the wrong format, and `ChunkerOptionError` when a
syntactically valid option is unusable (for example, invalid CSS).

## Options

`SectionOptions`, shared by `docx` and `html`:

| Option | Type / default | Effect |
| --- | --- | --- |
| `heading_based` | bool, `True` | Group blocks into heading-delimited sections. `False` emits one section; heading text becomes body text. |
| `max_heading_level` | int 1-9, `6` | Headings deeper than this level are body text. |
| `include_tables` | bool, `True` | Include table content. `False` omits tables. |
| `table_format` | `markdown` or `html`, `markdown` | How tables are rendered into chunk text. |
| `include_heading_path` | bool, `True` | Prefix each chunk with its heading path and a blank line. The path is always in `metadata["section_path"]`. |

`DocxOptions` adds `drop_toc` (bool, `True`): skip paragraphs whose style name
or id starts with `TOC`.

`HtmlOptions` adds:

| Option | Type / default | Effect |
| --- | --- | --- |
| `content_selector` | string / `None` | CSS selector for the content root. Empty means the whole body. No match raises `EmptyDocumentError`. |
| `remove_selectors` | string / `None` | Comma-separated CSS selectors removed after the root is chosen. Invalid syntax raises `ChunkerOptionError`. |
| `remove_boilerplate` | bool, `True` | Remove navigation, headers, footers, sidebars, forms, controls, landmark roles, and `aria-hidden="true"` elements. |
| `include_links` | bool, `True` | Render inline anchors as `[text](href)`; never fetches URLs. |

Every option has a default; `extra="forbid"` turns a misspelled option into a
validation error. `describe_options` rejects nested models, arrays, required
fields, and unsupported types.

## Section and offset semantics

- Blocks before the first heading form a section with an empty heading path.
- A heading closes the previous section; sibling headings do not inherit the
  previous sibling's children. Consecutive headings with no body produce no
  empty section.
- A section body that fits `chunk_size` becomes one chunk; a larger body is
  split with the recursive splitter. `chunk_overlap` applies inside a body,
  never across section boundaries.
- `metadata["section_path"]` uses the Markdown chunker convention, for example
  `["H1#Policy", "H2#Scope"]`.
- `source_offset` is relative to the section body, not the whole document.
  This matches the Markdown chunker; parsers cannot provide reliable global
  offsets after layout normalization.
- Chunk IDs are content hashes of document id, source version, ordinal, and
  text. Changing options changes the IDs, which is intended.

## Limitations

- Legacy Word `.doc` (OLE/CFB) and encrypted OOXML are rejected; save as
  `.docx`.
- DOCX covers the main body only. Headers, footers, footnotes, comments, and
  text boxes are excluded. Merged cells repeat their text through `row.cells`,
  preserving column alignment.
- HTML `colspan`/`rowspan` are not expanded; images and alt text are ignored;
  a nested table contributes its text to the outer cell.
- PDF extraction is text-only; scanned pages need OCR before chunking.
- A heading-path prefix is added after sizing, so a chunk body can exceed
  `chunk_size` by the prefix length.
