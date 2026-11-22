# Add a governance document parser

## Use when

A governed knowledge-base project must ingest a format the package does not
parse yet: scanned PDF or images (OCR), OFD, HTML, legacy Word, or a
vendor-specific archive export. The package already parses text/Markdown, text
PDF and DOCX; prefer those when the source supports them.

Profile: `rag_governance`.

## Do

### 1. Implement the Parser protocol

The parser turns bytes into structural blocks before cleaning, masking and
chunking. Return `ParsedDocument` with `ParsedBlock` values:

```python
# app/governance_parsers.py
from pydantic import BaseModel

from cliver_playbook.app.rag_governance.stages.base import (
    ParsedBlock,
    ParsedDocument,
    SourceDocument,
)


class EmptyOptions(BaseModel):
    pass


class OfdParser:
    name = "ofd"
    version = "1"
    options_model = EmptyOptions

    def parse(self, document: SourceDocument, options=None) -> ParsedDocument:
        del options
        blocks = _read_ofd(document.content)  # list[ParsedBlock]
        return ParsedDocument(blocks=blocks, metadata={"page_count": _page_count})
```

Use these block kinds:

| Kind | Meaning |
|---|---|
| `heading` | Starts a section; set `level` 1–6. |
| `text` | Body paragraph or OCR text block. |
| `table` | Rendered table text; keep the source order. |
| `page_break` | Flushes the current parent and starts a new page. |

Put page information in `locator` (`{"page": 12}`, or
`page_start`/`page_end` for a block spanning pages). The section builder
aggregates it into the parent/chunk `locator`. Represent a clause as a
`heading` block whose title begins with the clause label (for example
`第十二条 档案保管期限`); the builder records it as `clause`. Format-specific
facts belong in the block's `metadata`. Do not strip page boundaries: they
are what keeps citations page-accurate.

### 2. Register a project-specific name

```python
from cliver_playbook.app.rag_governance.stages.parser import parsers

parsers.register("ofd", OfdParser)
```

Import the module during app startup, before the governance worker claims its
first job. A duplicate name raises; use a project-specific name, not `pdf`,
`docx` or `text`.

### 3. Select it in project config

```json
{"parsing": {"parser": "ofd"}}
```

`auto` (the default) selects `text`, `pdf` or `docx` from MIME type and
filename. An explicit name is the escape hatch for formats whose MIME is
unreliable; an unknown name fails the ingest job loudly.

### 4. Keep the locator contract

The pipeline cleans and masks each block separately so a redaction cannot
shift a page boundary. Keep parser blocks in source order and keep page breaks
between pages. If OCR produces a page image plus text, emit the text blocks as
the retrieval content and put the page/box in `locator`; do not emit the image
bytes as text.

## Verify

Create a source and ingest a real sample through the governance API. Confirm:

- the staged document metadata contains `parser_id` equal to your
  `name@version`;
- parent and chunk metadata contain the expected `structure_path` and
  `locator` (page range and/or clause);
- a governed query returns a citation that resolves to the right page/clause;
- re-ingesting the same file is idempotent and a parser failure fails the job
  with a readable reason.

Run the package tests plus a project integration test with one representative
file per new format.

## Pitfalls

- **Do not parse after masking.** The parser needs the original bytes; the
  pipeline masks each parsed block before anything is stored.
- **Do not drop `page_break`.** A parser that joins pages loses page-accurate
  citations; a citation to the whole document is not a locator.
- **Do not fork a built-in parser.** Add a new registry name and keep the
  built-ins intact; a reusable parser belongs upstream.
- **Do not trust a vendor MIME type.** Select the parser explicitly in
  `parsing.parser` when the extension/MIME pair is ambiguous.
- **OCR quality is a separate gate.** Evaluate OCR text independently; a
  confident answer over bad OCR is still wrong.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-rag-governance/src/cliver_playbook/app/rag_governance/stages/base.py`
  — `ParsedBlock`, `ParsedDocument`, `Parser`, `SourceDocument`.
- `var/playbook/packages/backend/cliver-playbook-app-rag-governance/src/cliver_playbook/app/rag_governance/stages/parser.py`
  — the parser registry, built-ins, and `auto` selection.
- `var/playbook/packages/backend/cliver-playbook-app-rag-governance/src/cliver_playbook/app/rag_governance/ingestion/parent_child.py`
  — `split_parsed_blocks`, `structure_path` and locator construction.
- `var/playbook/packages/backend/cliver-playbook-app-rag-governance/src/cliver_playbook/app/rag_governance/ingestion/pipeline.py`
  — per-block cleaning/masking and persistence.
- Deep dive: `reference/decision-guide.md` section "Custom governance parser".
