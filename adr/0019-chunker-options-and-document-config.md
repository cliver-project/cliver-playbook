# ADR-0019: Configurable chunkers and per-document chunker configuration

**Status:** Accepted (2026-10-19).
**Context:** ADR-0018 established the chunker as the first of five pluggable
RAG stages, with `recursive`, `markdown`, `code` and `pdf` implementations.
Two gaps surfaced in use. A Word `.docx` sent to `recursive` failed because
the chunker decoded the ZIP package as UTF-8, and there was no HTML-aware
chunker, so policy pages lost heading structure while navigation and footers
entered the chunks. The output shape also varies by format — heading-based
sections, table rendering, page-chrome removal, link handling — and the web UI
had no way to choose. A chunker named only by a stage name cannot express that
variation without either a flag bag on every implementation or a parser that
guesses the format. The design also had to answer whether recording how a
document was chunked requires a fourth table.

## Decision

1. **Format-specific chunkers share structure-aware helpers.** `docx` reads
   the OOXML body in document order with `python-docx`; `html` walks the DOM
   with BeautifulSoup's stdlib parser. Both emit heading, text and table blocks
   into `chunking/sections.py`, which builds heading-delimited sections and
   splits each section body with the same recursive splitter as the default
   chunker. `chunking/tables.py` renders tables as Markdown or HTML and splits
   an oversized table by whole body rows, repeating the header in every part.
2. **Every chunker declares a flat options model.** `Chunker.options_model` is
   the single source of truth for configurable output. Option models are flat
   Pydantic models with primitive fields, defaults, and `extra="forbid"`;
   `describe_options` converts one into UI descriptors and raises on nested
   models, arrays, required fields, or unsupported types. Chunkers with fixed
   output use `EmptyOptions`. A chunker without `options_model` still works; it
   rejects options only if options were supplied.
3. **The effective configuration is one JSONB column on the document, not a
   fourth table.** `rag_documents.chunker_config` stores
   `{version, chunk_size, chunk_overlap, options}`: the chunker implementation
   version, the sizes used, and the validated option values including defaults.
   It is 1:1 with the document, replaced atomically with the chunks on
   re-upload, and never queried independently. A separate table would add a
   join without enforcing a new invariant; typed columns would need a migration
   per option. Rows written before the column existed carry `{}`, which the
   read schema fills with defaults.
4. **Re-chunking is re-uploading the original file.** The document id hashes
   the source name and file content, so the same file with different options
   updates the same row, increments its version, deletes the old chunks and
   embeddings, and writes the new configuration. No raw file is stored. A
   fourth table becomes justified only when an invariant changes: multiple
   embeddings per chunk, raw-file re-chunk without re-upload, document version
   history or rollback, or per-document ACLs/collections.
5. **Bad requests and bad files are different failures.** `chunker_options` is
   a JSON object capped at 4 KiB. Malformed JSON, a non-object payload, an
   unknown option, an option on a chunker without an options model, or an
   invalid CSS selector returns 422 and writes no failed document row. A wrong
   or legacy input (`ChunkerInputError`, notably `.doc`) returns 422 with an
   actionable message and records a failed row only when the document did not
   previously exist. An empty parse keeps `empty_after_parse`. A rejected
   re-upload never destroys a live indexed document.
6. **The web UI renders controls from the stage catalog.** `GET
   /api/v1/rag/stages` includes each chunker's `config_schema`; the upload page
   maps one descriptor to one control and keeps drafts per chunker so switching
   preserves edits. Selecting a `.docx` or `.html`/`.htm` file switches the
   chunker automatically when that chunker is registered; the user can
   override. The resolved defaults are sent with the upload so the persisted
   configuration describes exactly what produced the chunks.
7. **The `chunking/` folder is self-contained and copy-friendly.** Internal
   imports are relative, third-party parsers are imported lazily inside
   `split`, and nothing imports the rest of `cliver_playbook`.
   `chunking/README.md` is the usage reference for the contract, dependencies,
   options, offsets and limitations.

## Why

- Direct parsing preserves the structure retrieval depends on — Word outline
  levels, document order, HTML headings and tables — and avoids a second lossy
  parse cycle.
- One flat option contract serves the server, the UI and copy-paste consumers;
  a new option is a backend-only change.
- Configuration is an attribute of the document's current chunk set, not an
  independently queried entity, so the three-table model remains sufficient.
- Re-upload matches the product flow and avoids storing and serving raw files.

## Alternatives considered

- **Extend `recursive` to sniff formats and decode ZIP/OOXML/HTML.** Rejected:
  one implementation would mix container detection, format parsing, structure
  extraction and text splitting, and its options would apply only to some
  inputs.
- **Make Markdown conversion a mandatory pre-stage.** Rejected: Markdown cannot
  represent merged cells, column spans, footnotes, text boxes, headers/footers,
  or language metadata without a private extension syntax, and every format
  would need a converter plus a Markdown parser. It can still be added later as
  an optional normalization stage without changing the chunker contract.
- **A fourth table for chunker configuration.** Rejected: the column is 1:1
  with the document and never queried alone.
- **Typed columns for each option.** Rejected: options differ by chunker and
  every new option would need a migration.
- **Server-wide per-chunker defaults in `app.yaml`.** Out of scope: defaults
  come from the option model and the resolved values are recorded per document.
- **A generic JSON-Schema form renderer.** Rejected: recursive widget mapping
  and validation translation are not justified by the flat option contract.

## Non-goals

- Raw-file storage, one-click re-chunk without re-upload, or chunk-set version
  history.
- Legacy Word `.doc`, encrypted OOXML, or OCR for scanned PDFs and images.
- Multiple embeddings per chunk or per-document ACLs/collections.
- Fetching or resolving URLs found in HTML.
- Image alt text in HTML (currently ignored).

## Risks

- Option models must stay flat. `describe_options` and its tests fail loudly on
  unsupported shapes, so a new option cannot silently render as an unusable
  control.
- Word heading styles vary by locale and authoring tool. Detection tries
  `w:outlineLvl`, then the built-in English style id, then the style name, and
  treats anything else as body text.
- The HTML walker can duplicate or drop text at nested blocks; tests pin nested
  lists, paragraphs and containers.
- CSS selectors are user input. Uploads are size-capped, selector syntax errors
  become `ChunkerOptionError`, and no URL is fetched.
- A heading-path prefix is added after sizing the body, so a chunk can exceed
  `chunk_size` by the prefix length. The prefix is bounded by heading depth.
