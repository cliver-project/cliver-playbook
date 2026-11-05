# ADR-0023: RAG governance loop as a reusable package

**Status:** Accepted (2026-11-05).
**Context:** `cliver-playbook-app-rag` is a generic engine: documents,
chunking, embeddings, retrieval, reranking and generation. Deployments need a
lifecycle around that engine — a project per knowledge-base scenario, intent
rules, a golden dataset that gates change, staged ingestion with an approval
gate, document-level access control, evaluation, and read-only live tools for
data that must not be embedded. Building that lifecycle inside `rag` would make
every RAG consumer inherit governance policy; building it per application
forks the loop and lets the copies drift. The loop must therefore be one
reusable package that composes on top of `rag`, while `rag` itself gains only
the primitives that are useful without governance.

## Decision

1. **A new package owns the loop (D1, D11).** `cliver-playbook-app-rag-governance`
   depends on `basic <- user <- rag`; `rag` never imports governance. A
   scenario is project configuration plus optional registered stages and
   tools — never a code fork. The package owns projects, sources, golden sets,
   intent rules, evaluation, batches, approvals, jobs, clearance/ACL, the tool
   contract and the governed query facade.
2. **Generic primitives live in `rag` (D2, D4, D5).** `rag` gains document
   `logical_id`/`version` lineage, typed `classification`, `collection_id`,
   `metadata_json`, `published`, `source_updated_at`, `content_hash` and
   `deleted_at`; a `rag_chunk_parents` table with `rag_chunks.parent_id`; a
   retrieval-side `rag_chunks.search_text` distinct from the raw `text`; and a
   composite primary key `(chunk_id, embedder_version)` on
   `rag_chunk_embeddings` so one chunk can carry several models. None of these
   is governance-specific: they describe documents, parents and embeddings.
3. **Generation reads the original parent; contextual text is retrieval-only
   (D3).** A child chunk is the search unit. The LLM-written contextual text
   is prepended to `search_text` only; the generator receives the original
   parent section. This follows contextual-retrieval and parent-document
   practice, keeps answers traceable to source text, and prevents an
   ingestion-time model error from becoming the quoted answer.
4. **Publication is an SQL predicate, not a UI state (D6).** Every governed
   retrieval applies `published = true`. Staged rows are visible only through
   an explicit `allow_staged` access scope, which the API grants only to the
   separate `rag_governance:staged:read` capability. A caller cannot leak
   unapproved data by forgetting a filter in a template.
5. **Intent rules compile to a typed filter AST (D7).** A rule's scope is a
   leaf `{field, op, value}` or a boolean tree of `and`/`or`/`not`. The rule
   engine evaluates it without a database; retrieval compiles it to a
   SQLAlchemy expression with bound parameters. User or model text is never
   interpolated into SQL, and field/operator choices stay auditable.
6. **Approval is a per-project mode (D8).** Batches are reviewed as a unit by
   default. A project selects `manual`, `auto`, or `hybrid`: dynamic projects
   skip the gate, and hybrid reviews the first load while auto-publishing
   routine deltas that pass the hard gates. The mode is project
   configuration, not a process-wide setting.
7. **Golden sets are immutable once confirmed (D9).** Editing a confirmed
   golden set creates a new version. Every evaluation names the exact golden
   version and rule version it ran against, so a pass or failure is
   reproducible after both have moved on.
8. **The job runtime is a database table (D10).** Queued ingestion,
   evaluation and sync work lives in a job table claimed by an in-process
   worker, with an optional CLI worker. Jobs survive restarts and need no new
   infrastructure; the same runtime serves every project.
9. **Access is clearance plus explicit grants (D12).** A document is readable
   when the viewer's clearance meets its `classification` or a
   `gov_document_acl` row grants that viewer or role. A `NULL` classification
   fails closed: only an explicit grant exposes it. Tool bindings apply the
   same clearance check and may additionally require a permission code.
10. **API sources split by answer authority, not transport (D13).** Data whose
    passage is the citation and changes slowly is ingested. Data whose current
    value is the answer — balances, aging, order status — is served by a
    read-only query-time tool. Every live source still contributes a small
    capability/definition document so the planner knows the metric and tool
    exist. A stale embedded copy of a live number is never treated as
    authoritative.
11. **The model sees curated composites, never vendor tools (D14).** A tool
    binding names a project-level tool; the model cannot reach the vendor
    namespace. The planner is handed only bindings that pass
    `tool_authorized` — enabled, read-only, and within the viewer's permission
    code, minimum clearance and scope — so an unauthorized tool is never in
    the model's choice set. `RestrictedToolInvoker` then enforces the allowed
    name set per call: the project's authorized tools at the top level, and a
    composite's declared `dependencies` on the nested handle. Composites do
    not nest. The registry refuses write tools, caps result rows, and masks
    once at the top boundary; nested vendor calls are audited under the
    composite's `call_id`.
12. **The finance/Kingdee scenario is the reference vertical slice (D14).**
    `examples/finance_kpi/` contains seed documents, a versioned metric
    catalog, intent rules, a six-case golden set, and composite tools
    registered explicitly at composition time. Core governance imports no
    scenario module and registers no `finance_*` tool. The default backend is
    a contract-compatible mock Kingdee MCP server; a live deployment points
    the same client at the pinned third-party KingdeeMCP server, validates
    `tools/list`, and rejects a profile that admits a write tool.
13. **Live-tool evaluation pins time and asserts structure (D15).** A golden
    case that expects a live tool pins `as_of`/period and asserts tool routing
    plus numeric tolerance. It never asserts a wall-clock-relative value.
    Freshness is a hard gate. A closed-period result may legitimately be older
    than the reference instant; a result dated after it is rejected.
14. **The MCP SDK is an optional extra.** The outbound adapter speaks the
    JSON-RPC shapes over `httpx`, so core governance installs and tests with
    no MCP package present. `mcp-client` adds the SDK for deployments that
    want its stdio/session helpers. The inbound `cliver-playbook-app-mcp`
    server is a separate concern and is never imported here.

## Why

- **Reuse is the product.** The closed loop — rules, golden set, evaluation,
  approval, publication, governed tools — is the same for customer service,
  logistics and finance. Only the project configuration, the corpus, the
  catalog and the composites change. Keeping that contract in one package is
  what makes the second scenario cheaper than the first.
- **The engine stays an engine.** `rag` can be deployed without governance,
  and its new primitives are meaningful on their own (lineage, parents,
  collection scope, multi-model embeddings). Governance policy — approval,
  evaluation thresholds, tool authority — stays in the layer that owns it.
- **Failures are forced into the open.** Publication in SQL, fail-closed
  clearance, typed filters, declared composite dependencies and hard
  freshness/leak gates all turn a class of silent data leak into a test
  failure or a refused call.
- **The reference slice is executable evidence.** Because the mock speaks the
  curated vendor contract and the composites are scenario code, the full loop
  runs in CI with no ERP credentials while the production integration keeps
  the same client and tool boundaries.

## Alternatives considered

- **Grow the loop inside `rag`.** Rejected: every RAG deployment would inherit
  approval gates, clearance columns and golden-set machinery it may not want,
  and `rag`'s API would become the union of all governance policy.
- **Fork the loop per customer.** Rejected: the copies drift, evaluation
  semantics diverge, and a fix in one does not reach the others.
- **Filter staged or restricted rows in the UI.** Rejected: any other caller
  of the same query path bypasses it. The predicate must be in the SQL the
  retriever builds.
- **Embed live ERP values on a schedule.** Rejected: a stale balance is worse
  than no balance because it looks authoritative. The capability document
  carries the definition; the tool carries the value and its `as_of`.
- **One approval mode for all projects.** Rejected: a first load needs review
  in a way a routine delta does not, and some projects are deliberately
  dynamic. The mode is a project property.
- **Let the model call Kingdee tools directly.** Rejected: the vendor surface
  includes writes, unbounded row sets and raw `filter_string` composition.
  Curated composites with typed arguments and declared dependencies are the
  only path.
- **Mutable golden sets.** Rejected: a historical evaluation could no longer
  be interpreted. Versions are cheap; irreproducible pass/fail is not.
- **Require the MCP SDK unconditionally.** Rejected: it makes the core package
  heavier and its installability depend on an optional integration. The
  JSON-RPC adapter keeps the extra genuinely optional.

## Risks

- **Rule and golden-set drift.** A changed rule without a re-run makes the
  recorded evaluation stale. The project lifecycle requires a golden run
  after a rule change; the report names the rule version it covered.
- **The mock and the vendor drift apart.** The mock implements a curated,
  versioned contract and is validated against pinned fixtures; upgrading
  KingdeeMCP is a deliberate change that runs the contract test and a staging
  smoke test.
- **Live tool failure.** The facade narrates "live data unavailable" and never
  substitutes a snapshot unless the tool binding explicitly allows a labelled
  fallback.
- **Clearance is only as good as ingestion metadata.** A document ingested
  with the wrong classification is mis-scoped; the approval preview and the
  classification-4 leak probes exist to catch that before publication.
