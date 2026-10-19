# ADR-0019: Configurable chunkers and per-document chunker configuration

**Status:** Accepted (2026-10-19).
**Context:** ADR-0018 established the chunker as the first of five pluggable
RAG stages, with `recursive`, `markdown`, `code` and `pdf` implementations.
Two gaps surfaced in use. First, a Word document sent to `recursive` failed:
`.docx` is a ZIP package, and the chunker decoded the raw bytes as UTF-8.
There was no HTML-aware chunker either, so policy pages lost their heading
structure and navigation boilerplate entered the chunks. Second, the shape of
the output genuinely varies by format — heading-based sections, table
rendering, page-chrome removal, link handling — and the web UI had no way to
choose. A chunker named only by a stage name cannot express that variation
without either a flag bag on every implementation or a parser that guesses the
format.

The design also had to answer a data-model question: the RAG schema has three
tables (`rag_documents`, `rag_chunks`, `rag_chunk_embeddings`). Does recording
how a document was chunked require a fourth?

## Decision

1. **Format-specific chunkers share structure-aware helpers.** `docx` reads the
   OOXML body in document order with `python-docx`; `html` walks the DOM with
   BeautifulSoup's stdlib parser. Both emit a flat stream of heading, text and
   table blocks into `chunking/sections.py`, which builds heading-delimited
   sections and splits each section body with the same recursive splitter as
   the default chunker. `chunking/tables.py` renders tables as Markdown or
   HTML and splits an oversized table by whole body rows, repeating the header
   in every part. Direct parsing was chosen over converting every upload to
   Markdown first: the parser sees Word heading styles, table structure and
   HTML landmarks that a generic conversion either flattens or loses.
2. **Every chunker declares a flat options model.** `Chunker.options_model` is
   the single source of truth for configurable output. Option models are flat
   Pydantic models with primitive fields, defaults, and `extra="forbid"`;
   `describe_options` converts one into a list of UI descriptors and raises on
   nested models, arrays, required fields, or unsupported types instead of
   emitting a control the form cannot honour. Chunkers whose output is fixed
   declare `EmptyOptions`. A chunker without `options_model` (for example a
   third-party implementation written before this contract) still works; it
   rejects options only if options were actually supplied.
3. **The effective configuration is one JSONB column on the document, not a
   fourth table.** `rag_documents.chunker_config` stores
   `{version, chunk_size, chunk_overlap, options}`: the chunker implementation
   version, the sizes used, and the validated option values including defaults.
   The column is 1:1 with the document, is replaced atomically together with
   the chunks on re-upload, and is never queried independently — a separate
   table would add a join without enforcing a new invariant, and a typed column
   per option would require a migration for every new chunker option. Rows
   written before the column existed carry `{}`; the read schema fills it with
   defaults.
4. **Re-chunking is re-uploading the original file.** The document id hashes
   the source name and file content, so the same file with different options
   updates the same row, increments its version, deletes the old chunks and
   embeddings, and writes the new configuration. No raw file is stored. A
   fourth table becomes justified only when an invariant changes: multiple
   embeddings per chunk, raw-file re-chunk without re-upload, document version
   history or rollback, or per-document ACLs/collections.
5. **Upload validation distinguishes bad requests from bad files.** The
   `chunker_options` form field is a JSON object capped at 4 KiB. Malformed
   JSON, a non-object payload, an unknown option, or an option on a chunker
   without an options model returns 422 and writes no failed document row; an
   invalid CSS selector raises `ChunkerOptionError` and follows the same path.
   A wrong or legacy input (`ChunkerInputError`, notably `.doc`) returns 422
   with an actionable message and records a failed row only when the document
   did not previously exist. An empty parse keeps the existing
   `empty_after_parse` reason. A rejected re-upload never destroys a live
   indexed document.
6. **The web UI renders controls from the stage catalog.** `GET
   /api/v1/rag/stages` includes each chunker's `config_schema`; the upload page
   maps one descriptor to one control (`boolean` → checkbox, `integer` →
   number input, `string` → text input, enum → select) and keeps drafts per
   chunker so switching preserves edits. Selecting a `.docx` or `.html`/`.htm`
   file switches the chunker automatically when that chunker is registered,
   and the user can override the choice. The resolved defaults are sent with
   the upload, so the persisted configuration describes exactly what produced
   the chunks rather than leaving defaults implicit.
7. **The `chunking/` folder is self-contained and copy-friendly.** Every
   internal import is relative, third-party parsers are imported lazily inside
   `split`, and nothing imports the rest of `cliver_playbook`. Other projects
   can copy the folder or import it as a package. `chunking/README.md`
   documents the contract, dependencies, option semantics, offsets and
   limitations.

## Why

- Direct parsing preserves the structure the retrieval stage depends on:
  Word outline levels and built-in heading styles, document-order reading,
  HTML heading tags and tables. A mandatory Markdown conversion would add a
  second parser, a second failure mode, and a lossy intermediate
  representation for tables, footnotes, text boxes and page chrome.
- A flat options model gives the server, the UI and copy-paste consumers the
  same contract. The UI never hardcodes a chunker name or field, so a new
  option is a backend-only change.
- The JSONB column keeps the three-table model intact for the current scope:
  configuration is an attribute of the document's current chunk set, not an
  independently queried entity.
- Re-upload matches the actual product decision — users change how a file is
  chunked by uploading it again — and avoids storing and serving raw files.

## Alternatives considered

- **Extend `recursive` to sniff formats and decode ZIP/OOXML/HTML.** Rejected:
  one implementation would mix container detection, format parsing, structure
  extraction and text splitting, and its options would apply only to some
  inputs.
- **Make Markdown conversion a mandatory pre-stage.** Rejected for the same
  reasons as in Decision 1, and because Markdown cannot represent merged
  cells, column spans, footnotes, text boxes, headers/footers, or language
  metadata without a private extension syntax. It can still be added later as
  an optional normalization stage without changing the chunker contract.
- **A fourth table for chunker configuration.** Rejected: the column is 1:1
  with the document, is never queried alone, and a table would only move the
  same row to another relation.
- **Typed columns for each option.** Rejected: every new chunker option would
  need a migration, and options differ by chunker.
- **Server-wide per-chunker defaults in `app.yaml`.** Out of scope: the
  effective defaults are derived from the option model, and the document
  records the resolved values. A per-chunker default layer can be added later
  without changing the stored shape.
- **A generic JSON-Schema form renderer.** Rejected: it would need recursive
  widget mapping, validation translation and layout rules for a benefit only
  hypothetical third-party chunkers would see. The flat descriptor contract is
  deliberately smaller.

## Non-goals

- Raw-file storage, one-click re-chunk without re-upload, or chunk-set version
  history.
- Legacy Word `.doc`, encrypted OOXML, or OCR for scanned PDFs and images.
- Multiple embeddings per chunk or per-document ACLs/collections.
- Fetching or resolving URLs found in HTML.
- Image alt text in HTML (currently ignored).

## Risks

- Option models must stay flat. `describe_options` and its tests fail loudly
  on nested models, arrays, required fields, and floats, so a new option
  cannot silently render as an unusable control.
- Word heading styles vary by locale and authoring tool. Heading detection
  tries `w:outlineLvl`, then the built-in English style id, then the style
  name, and treats anything else as body text.
- The HTML walker can duplicate or drop text at nested blocks. The walker
  emits a container's direct inline text once and descends only into nested
  blocks; tests pin nested lists, paragraphs and containers.
- CSS selectors are user input. Uploads are size-capped, selector syntax
  errors become `ChunkerOptionError`, and no URL is fetched.
- Merged DOCX cells repeat their text to preserve column alignment; HTML
  `colspan`/`rowspan` are not expanded. Both are documented rather than
  silently approximated.
- A heading-path prefix is added after sizing the body, so a chunk can exceed
  `chunk_size` by the prefix length. The prefix is bounded by heading depth and
  is normally far smaller than the body.
