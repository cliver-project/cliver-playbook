# cliver-playbook-app-rag-governance

A reusable governance loop over the `cliver-playbook` RAG stack: one project
per knowledge-base scenario, intent rules that decide retrieval scope and
tools, a golden dataset that gates change, staged ingestion with an approval
gate, document-level access control, and a query facade that enforces both
document clearance and tool authority.

The package composes on top of `cliver-playbook-app-rag` and never replaces
it. Documents, chunks, embeddings and retrieval stay owned by `rag`; this
package adds the project-level lifecycle around them. Package chain:

```
cliver-playbook-app-basic <- cliver-playbook-app-user
  <- cliver-playbook-app-rag <- cliver-playbook-app-rag-governance
```

Full design: `docs/superpowers/specs/2026-11-05-rag-governance-loop-design.md`
(local-only) and ADR-0023.

## What is inside

| Area | Module | Responsibility |
|---|---|---|
| Projects | `services/projects.py`, `api/projects.py` | Project row and versioned configuration: scope strategy, retrieval knobs, embedder, thresholds, approval mode. |
| Sources and batches | `services/sources.py`, `services/batches.py`, `api/sources.py`, `api/batches.py` | Source definitions, ingestion batches, staged rows and the publish transition. |
| Ingestion | `ingestion/`, `stages/parser.py` | Parsing (text/PDF/DOCX), masking, parent/child splitting with structure/page locators, contextual prefixes, embedding and staging. |
| Golden sets | `golden/`, `api/golden.py` | Candidate generation, JSONL codec, immutable confirmed versions, per-case edits. |
| Intent rules | `rules/`, `api/rules.py` | Priority-ordered keyword/regex rules, typed filter-AST scopes, `none`/`retrieval`/`tools`/`agentic` strategies, and an optional System One router with keyword fallback. |
| Evaluation | `evaluation/`, `api/evaluations.py` | Runner, evaluators, hard gates, thresholds, case-level and aggregate reports. |
| Approvals | `services/approvals.py`, `api/approvals.py` | Approve/reject a staged batch, audit, publish or discard. |
| Jobs | `runtime/jobs.py`, `runtime/handlers.py` | DB-backed queue, in-process worker, and the canonical handlers for `ingest_batch`, `run_eval` and `generate_golden`. |
| Access | `services/access.py`, `query/access.py`, `rag.access` | `AccessScope`, clearance comparison, explicit document grants, staged preview. |
| Tools | `tools/` | `ToolRegistry`, `ToolSpec`, `RestrictedToolInvoker`, composite dependencies, masking, audit, MCP and HTTP-OpenAPI adapters. |
| Query facade | `query/facade.py`, `api/query.py` | Intent recognition, retrieval, parent lookup, live tool calls, generation and observations. |
| Runtime app | `app.py`, `settings.py`, `settings_section.py` | Standalone composition, settings block and runtime settings section. |
| Migrations | `alembic/`, `migrate.py` | Own chain and version table `alembic_version_rag_governance`. |
| Test/demo doubles | `testing/mock_kingdee/` | Contract-compatible mock of the curated Kingdee read-only MCP tool set. |
| Reference scenario | `examples/finance_kpi/` | Seed corpus, metric catalog, rules, six-case golden set, composite tools, fixtures. |

## Composition

A product build includes the package's routers in its own app (ADR-0015):

```python
from cliver_playbook.app.rag_governance import ROUTERS as GOVERNANCE_ROUTERS

for router in GOVERNANCE_ROUTERS:
    app.include_router(router)
```

`create_app()` in `cliver_playbook.app.rag_governance.app` assembles the
standalone stack (`basic + user + rag + governance`) for development and
tests. It binds the most-derived `Settings` with the runtime, so every
package's `settings` proxy sees the same instance (ADR-0016). Its lifespan
also starts the in-process job worker (`rag_governance.worker_enabled`,
default on) so the 202 endpoints actually execute; a deployment that runs
its own worker sets the flag false. The factory puts an empty `ToolRegistry`
and the rule-based `RuleToolPlanner` on `app.state`; a scenario registers
its composite tools there at startup:

```python
from examples.finance_kpi.tools import register

register(app.state.tool_registry)  # after the vendor MCP tools are registered
```

Importing `rag_governance` registers its permission codes and settings section
before any router that references them, and reads no settings or database.

## Settings

The process-wide block is `rag_governance` (`CLIVER_RAG_GOVERNANCE__*`);
project policy — approval mode, retrieval knobs, thresholds, tool bindings —
lives on the project row, not here.

| Field | Default | Meaning |
|---|---|---|
| `worker_enabled` | `true` | Run the in-process job worker. |
| `worker_poll_seconds` | `1.0` | How often the worker claims a queued job. |
| `job_max_attempts` | `3` | Failures before a job is marked failed. |
| `job_retry_backoff_seconds` | `2.0` | Base delay; doubles per attempt. `0` is test-only. |
| `default_approval_mode` | `manual` | Used only when a new project chooses no mode. |
| `mock_kingdee_url` | empty | Optional base URL of a local mock ERP for scenario startup code; empty disables it. |
| `max_tool_rows` | `1000` | Upper bound on rows a governed tool may return. |

Runtime edits go through the standard settings section
(`rag_governance` → Admin → Settings) and apply in place.

## Permissions

Registered at import into the identity catalog:

| Code | Gates |
|---|---|
| `rag_governance:project:read` / `:write` | Viewing and editing projects. |
| `rag_governance:source:write` | Managing sources and triggering ingestion. |
| `rag_governance:golden:read` / `:write` | Viewing, editing, importing and confirming golden sets. |
| `rag_governance:rule:read` / `:write` | Viewing, editing and activating intent rules. |
| `rag_governance:eval:read` / `:run` | Viewing and running evaluations. |
| `rag_governance:approve` | Approving or rejecting a staged batch. |
| `rag_governance:staged:read` | Previewing unapproved staged documents. |
| `rag_governance:tool:read` / `:write` | Viewing and editing tool bindings. |
| `rag_governance:job:read` | Viewing background jobs. |
| `rag_governance:query:read` | Asking governed questions. |

`staged:read` is deliberately separate from `project:read`: seeing unapproved
data is the capability the approval gate withholds.

## Migrations

The package owns its chain; `migrate.py` is the aggregate entry point that
runs every dependency's chain first (`basic`, `user`, `rag`, then governance):

```bash
python -m cliver_playbook.app.rag_governance.migrate \
  --database-url postgresql+psycopg://cliver:cliver@127.0.0.1:15432/cliver_app
```

Omit `--database-url` to use the configured `database_url`
(`CLIVER_DATABASE_URL` / `app.yaml` / `.env`). Re-running is a no-op once the
database is current.

## Local demo (isolated ports)

Other services on this machine may own 5432, 8000 and 5173. The demo uses
offset ports: demo database `127.0.0.1:15432`, standalone app
`127.0.0.1:18000`, mock Kingdee `127.0.0.1:18080`, web UI
`127.0.0.1:5174`.

From the repository root:

```bash
# 1. Stack: demo PostgreSQL (compose), every migration chain, the mock
#    Kingdee server, and the finance scenario app (worker + tools + LLM).
make gov-demo-up

# 2. Scenario data, in a second terminal: project, confirmed golden set,
#    proposed rules, one staged ingest, role clearance and tool bindings.
#    The seeded admin must change password on first login, so pass both.
make gov-demo-seed ADMIN_PASSWORD=… ADMIN_NEW_PASSWORD=…

# 3. Web UI (governance pages, proxied to :18000).
make gov-demo-web
```

The app is `examples/finance_kpi/app.py:create_demo_app` — the governance
factory plus the scenario's tool registration, the filename-based taxonomy
stage (`examples/finance_kpi/stages.py`) and the in-process job worker
(`rag_governance.worker_enabled`, on by default). Generation uses the local
ollama endpoint unless `GOV_LLM_BASE_URL` / `GOV_LLM_MODEL` /
`GOV_LLM_API_KEY` say otherwise; without a model the facade still answers
with a verbatim-context stub and full citations. A reasoning model needs a
larger `max_tokens` on the query (the UI defaults to 4096) — the hidden
reasoning otherwise consumes the whole budget and the answer text comes
back empty.

The demo storyline in the UI (or through the API):

1. **Intent rules** — inspect the proposed rule set; try the matcher.
2. **Sources & ingestion** — the seeded corpus is staged, not searchable.
3. **Evaluations** — run a baseline over the confirmed golden set with the
   staged batch as its evidence (`batch_id`); the run id is recorded on the
   batch, which is what the approval gate verifies.
4. **Approvals** — approve: the batch's documents publish (prior versions
   of the same logical ids unpublish), and the project turns `active`.
5. **Intent rules** — activate the proposed set against the passing run.
6. **Governed query** — ask a question; the trace shows the intent, the
   strategy, live tool rows, citations with locators, and the as-of.

Re-seeding converges configuration (project config, golden set, source,
proposed rules) and never stages the corpus twice. A full reset is
`make gov-demo-down` followed by
`docker compose -f docker-compose.gov-demo.yml down -v`.

The mock accepts JSON-RPC `initialize` / `tools/list` / `tools/call` at any
path, so a tool binding can point at `http://127.0.0.1:18080/mcp`. The
composites are registered by the scenario at composition time, not by core
governance; `tests/test_finance_acceptance.py` shows the same wiring in a
test. The manual commands behind the targets:

```bash
GOV_DB_PORT=15432 docker compose -f docker-compose.gov-demo.yml up -d --wait db
uv run python -m cliver_playbook.app.rag_governance.migrate \
  --database-url postgresql+psycopg://cliver:cliver@127.0.0.1:15432/cliver_app
uv run python -m cliver_playbook.app.rag_governance.testing.mock_kingdee.server \
  --fixtures examples/finance_kpi/fixtures/kingdee --period 2026-10 --port 18080
cd packages/backend/cliver-playbook-app-rag-governance && \
  CLIVER_DATABASE_URL=postgresql+asyncpg://cliver:cliver@127.0.0.1:15432/cliver_app \
  CLIVER_RAG__LLM=cliver-core \
  uv run python -m uvicorn --factory examples.finance_kpi.app:create_demo_app \
    --host 127.0.0.1 --port 18000
```

The reference scenario's fixtures are pinned to period `2026-10` with a data
cutoff of `2026-10-31T23:59:59+08:00`; questions use the injected `as_of`,
never the host clock, so the demo is reproducible on any day.

## Test

```bash
uv run pytest -v
```

The suite runs on a temporary SQLite database with no services required; the
PostgreSQL-specific migration test renders SQL offline. `ruff check` and
`ruff format --check` are the lint gates.

## Optional MCP client

The outbound `mcp-tool` adapter speaks JSON-RPC over `httpx` and works with no
MCP SDK installed. Install the extra only for a deployment that wants the
SDK's stdio/session helpers:

```bash
pip install "cliver-playbook-app-rag-governance[mcp-client]"
```

The inbound `cliver-playbook-app-mcp` server is a separate package and is
never imported here.
