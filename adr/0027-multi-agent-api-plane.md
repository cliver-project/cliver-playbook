# ADR-0027: Multi-agent API plane

**Status:** Proposed (2026-11-13).
**Context:** AI-native applications are not one model call. A product workflow
spans business points — products, profile, knowledge, orders, approvals — and
each point needs its own context, tools, evaluation and improvement loop. A
single monolithic agent makes those responsibilities hard to isolate, test,
evaluate and evolve. The API plane therefore needs to be a collaboration
platform: one coordinator that understands the request and delegates to
business-point sub-agents, while each sub-agent owns a repeatable pipeline that
can later observe its outcomes and improve.

The architecture exposed the pipeline seams first. The reference
self-enhancement implementation now lands behind those seams: a redacted
experience store, explicit feedback, persisted evaluations, evidence-backed
proposals, an approval/audit gate and a runtime prompt overlay. It does not
change the UI, run/event contracts or coordinator shape.

## Decision

1. **One coordinator, N sub-agents.** The coordinator is the public entry for an
   agent run. It plans, selects sub-agents, delegates, merges results and emits
   a typed event stream. Sub-agents own business points; they never render UI
   and never talk to the client directly.
2. **Sub-agents are a stable protocol, not a base-class hierarchy.** A
   `SubAgent` exposes `name`, `description`, `capabilities`, an autonomy policy,
   `can_handle(intent)` and `run(context) -> AgentResult`. The registry rejects
   duplicate names and blank descriptions. Projects register their own agents
   through the same seam; the shipped products/profile/general agents are
   examples.
3. **The coordinator planner is a seam.** The first implementation is
   deterministic (registry matching plus a fallback). AgentCore or an LLM
   planner replaces it later without changing the run/event contract. The UI
   never routes business logic.
4. **Every sub-agent declares a self-enhancing pipeline.** The contract has
   `observe`, `evaluate` and `improve` hooks plus an `AutonomyPolicy`
   (`allowed_sources`, `feedback_dataset`, `evaluation_metric`, a launch
   threshold, `improvement_mode` = off/proposal/auto, `require_approval` and
   `retention_days`). The reference `LearningPipeline` stores redacted
   experiences, scores them, creates at most one pending proposal per agent
   from sustained low scores, and applies approved prompt guidance on later
   runs. `auto` remains approval-gated; `NoopPipeline` stays available for
   tests and projects that have not opted in.
5. **A run store is a seam.** An in-memory store is the default; a persistent
   store can replace it without changing the API. Runs are user-scoped when
   authentication is enabled.
6. **Typed events are the UI contract.** The run stream emits
   `run.started`, `coordinator.plan`, `agent.selected`, `agent.delegated`,
   `agent.result`, `pipeline.evaluated`, `pipeline.improvement`,
   `message.delta`, `run.completed` and `run.failed`, alongside the existing
   tool/skill/MCP events. SSE carries an event id and sequence for resume.
7. **The API layer owns the collaboration; the UI is thin.** The web/desktop/
   mobile clients start a run and render events. A chat-first surface can route
   to feature screens from the typed intent, but direct routes remain.
8. **The rust BFF only proxies.** It forwards runs and streams to the Python
   agent service; it must not reimplement the coordinator, registry or
   pipeline semantics.
9. **The scaffold generates the skeleton, not the intelligence.** It creates
   the agents package, registry, coordinator, pipeline policy, run store,
   example sub-agents, endpoints, contracts and tests. The actual planner,
   business logic and self-enhancement belong to the project.

## Consequences

- A project starts with a coordinator/sub-agent structure instead of a single
  chat endpoint; adding a business point is registering a sub-agent.
- The event contract grows but stays one stream; UI and contract tests have a
  single place to assert delegation.
- The self-enhancing loop is real for the reference agents: user feedback
  changes an evaluation, low pass rates create a reviewed proposal, and an
  approved prompt overlay changes the next AgentCore run. The proposal
  generator and evaluator remain replaceable seams rather than fixed policy.
- More structure than a single agent; a trivial app can register only the
  general agent and still work.
- The coordinator's deterministic first version is intentionally modest; it
  proves the seams, not the final planning quality.

## Alternatives considered

- **One monolithic agent:** rejected — no business-point isolation, no clean
  evaluation or improvement boundary.
- **UI-side orchestration:** rejected — the UI would own routing, keys and
  business logic, and every client would drift.
- **A framework-owned control flow (for example a graph library):** rejected as
  the scaffold's contract — it hides the seams and makes the playbook a
  framework. A project may use one behind the coordinator.
- **Auto self-improvement from day one:** rejected — data autonomy, evaluation
  and approval are prerequisites. The reference loop creates proposals, never
  applies them without review, and has no offline regression gate yet, so
  `auto` is not enabled as an apply mode.
- **One run store in the UI:** rejected — runs are API state and must survive
  client reconnects.

## Implementation note (2026-11-13)

The planner and runner are separate seams. `Planner` returns a `PlanDecision`
from either the deterministic matcher or an AgentCore structured-output call;
every model failure falls back to deterministic routing. `AgentRunner` is
either the direct business path or an AgentCore Re-Act loop built from the
sub-agent's `toolkit(context)`. The loop streams the existing
`message.delta`/`tool.call`/`tool.result`/`usage` events and falls back to the
business path only when it fails before emitting anything. Skills, an MCP
client and a permission callback are opt-in through settings and run
resources. No event or endpoint shape changed.

Run state is now durable in the project's `agent_runs` table through an async
`DatabaseRunStore`, and every event is persisted to `agent_run_events` before
anything observes it. `POST /runs` starts one worker task: it claims the run
atomically (`queued → running`), drives the coordinator, persists each event,
honours cancellation even while the model is quiet, and heartbeats so another
process can detect an orphaned run. Streams never execute a run — they replay
the event log from `Last-Event-ID` (each SSE frame carries `id: <sequence>`)
and tail it until the terminal event, with keepalive comments while quiet.
Reconnects and concurrent readers therefore cannot repeat tool side effects,
and a crashed worker is marked failed (`orphaned`) instead of tailing forever;
orphaned runs are never retried automatically because tools may have had side
effects. The worker registry is process-local: behind multiple uvicorn workers
the claim still guarantees exactly-once execution and other processes tail the
log — replace `start_run_worker` with a job queue when that stops being
enough. The web, iOS and Android transports accept a last-event-id so clients
can resume.

The planner now returns an ordered multi-step plan (one sub-agent per step,
bounded by `agent_plan_max_steps`); the coordinator runs the steps sequentially
and passes earlier `AgentResult`s to each later step through
`context.prior_results`. Every runner event is tagged with the executing
`agent`, `agent.selected/delegated` carry the step index, and
`coordinator.plan` carries `steps` (the old single `intent` shape stays
readable as an optional field). Skills resolve per agent from a shared and an
agent-name directory, and a sub-agent's `AgentToolkit` may name its own MCP
servers. Parallel steps and direct agent-to-agent handoff are deliberately
later layers.

The optional System One selector is cliver-core's `SystemOneSelector` wired as
AgentCore's `candidate_selector`, so large tool/skill catalogues are narrowed
before they reach the main model. It supports an in-process laya backend
(`cliver-core[local-laya]`), Aliyun Bailian, TypeSafe Jev and any endpoint
speaking the shared `/v1/systemone` wire. Activation thresholds and the
per-candidate fit gate are settings; construction and calls fail open to the
full catalogue. Local providers are process-cached and closed on lifespan
shutdown. MCP *server* selection is still later; the selector only narrows the
tools that MCP exposes.

## Implementation note (2026-11-14): the self-enhancement flywheel

The reference loop is deliberately small enough to audit end to end:

1. **Observe.** After a sub-agent result the coordinator calls
   `LearningPipeline.observe`, which writes one `agent_experiences` row keyed by
   `(run_id, step, agent)`. Before insert it applies the policy's source
   allow-list, redacts sensitive keys (including non-exact names such as
   `user_email` or `mobile`) and email/phone/SSN-shaped text, hashes the raw
   session id, and prunes rows older than `retention_days`. Each plan step
   starts from the caller's declared sources, so one agent's data access cannot
   poison another agent's policy. A result from an undeclared source is
   dropped, not silently learned from.
2. **Evaluate.** `evaluate` combines result completeness with explicit user
   ratings (1-5) and persists the score/pass flag in `agent_evaluations` under
   the agent's metric. `evaluation_threshold` defaults to 0.6 — the "60-point
   launch bar" — and exactly 0.6 passes. A later user rating re-evaluates the
   same row, so the stored score reflects the latest outcome evidence.
   Concurrent ratings and evaluations resolve the unique slot by updating the
   winning row; anonymous feedback has a partial unique index, so it cannot
   silently multiply.
3. **Improve.** `improve` looks at the latest 50 evaluations for the agent. At
   least three samples below the launch bar create at most one pending
   `agent_improvements` proposal. The reference proposal is a legible
   verification/uncertainty prompt append with sample count, pass rate and
   negative-feedback evidence; it is a seam for a model-based distiller, not a
   claim that a generic sentence is optimal.
4. **Review.** `GET /api/v1/agent/proposals` and approve/reject are reviewer
   actions (`agent:improve` permission or the admin role). Every creation,
   approval, application and rejection writes `agent_improvement_events` with
   the actor. Prompt proposals apply atomically to `agent_configs`; tool and
   policy proposals are recorded as approved for a human code change, never
   executed by the approval endpoint. With authentication disabled (the
   local-only profiles) these endpoints are open; enable auth for any shared
   deployment.
5. **Close the loop.** The next `AgentCoreRunner` run loads the active
   `agent_configs.prompt_overlay` and appends it to the sub-agent's system
   prompt. The web chat exposes `Helpful` / `Not helpful` after a completed run
   and posts to `POST /api/v1/agent/runs/{run_id}/feedback`; iOS/Android can
   call the same contract. Feedback re-evaluates and may surface the pending
   proposal in the response.

The learning calls are fail-open: a database or pipeline failure is logged and
never turns a successful business result into a failed run. They also use a
dedicated database session, so observing a result cannot commit a tool's
in-flight transaction. Proposals require approval even in `auto` mode.

### Golden-set offline gate (2026-11-14)

Prompt proposals can now be gated by agent-scoped golden cases before they
apply. Each `agent_golden_cases` row has a message plus `expected_contains`
and `forbidden_contains` assertions; the reference gate is deliberately
assertion-based rather than an untested LLM judge. `agent_regression_runs`
stores one report per proposal with baseline and candidate scores and
per-case pass flags; every gate outcome is appended to the improvement audit.

At approval time, if at least one enabled case exists, the candidate overlay
must score at least as high as the current overlay and at least
`AutonomyPolicy.regression_min_score` (default 0.8). If cases exist but no
model runner is available, the gate fails closed with 409. With no cases the
gate is recorded as `skipped` and approval proceeds, preserving the
agent-only and no-model development path.

`AgentCoreCaseRunner` executes a case through the real AgentCore loop with
`prompt_overlay_override`, the agent's safe tools, a permission callback that
denies every ASK-category tool, MCP disabled, and a rejection of any
deterministic fallback (a fallback would not exercise the candidate prompt).
The gate is synchronous under the approval request for now; moving it to the
job runtime is a later scale step. Golden runs are user-less in this
reference, so an agent whose safe tools require a signed-in user needs a
dedicated evaluation identity in a later slice.

The golden set is intentionally independent of
`cliver-playbook-app-rag-governance`: the agent layer owns its cases and
reports, and an optional adapter can later consume RAG golden/evaluation
without making every AI-native app install the RAG stack. The review API is:

- `POST/GET /api/v1/agent/golden-cases`, `DELETE /golden-cases/{id}`
- `GET /api/v1/agent/proposals/{id}/regression`
- `POST /api/v1/agent/proposals/{id}/approve` returns the gate report in
  `regression` and refuses a failed/error report with 409.

### Model-based experience distillation (2026-11-14)

`app/agents/proposals.py` adds a `ProposalGenerator` seam. The default remains
the deterministic evidence-backed proposal; when `CLIVER_AGENT_LLM_*` is
configured, `AgentCoreProposalModel` asks AgentCore structured output to turn
the recent redacted outcomes, evaluation scores and feedback comments into a
`ProposalDraft` (title, rationale, prompt append). The model sees bounded
evidence (at most eight experiences, truncated fields), never raw user ids,
and is instructed not to change tools, permissions or safety rules.

Every provider, schema or length failure logs and falls back to the
deterministic proposal; the proposal evidence records
`proposal_source` (`agentcore`, `deterministic` or
`deterministic_fallback`) and the fallback reason. The same `agent_llm_model`
is reused, so there is no second provider configuration. Distilled text is
never auto-applied: it still requires approval and, when golden cases exist,
the offline gate. Distillation currently runs synchronously in the learning
hook; moving it to the job runtime is the next scale step. Projects can replace
the generator through the seam without changing the API or approval path.

Still later: per-agent dashboards and rollout/rollback controls, golden-set
versioning, and `feedback_dataset` wiring. Until then the scaffold does not
auto-apply improvements, and evaluator, generator and gate remain replaceable
seams.

Verified with 71 API tests in ai-web (25 learning/gate tests: redaction/source
enforcement, launch-bar evaluation, anonymous feedback upsert, proposal
creation/approval/rejection, model distillation and deterministic fallback,
runtime overlay injection, golden-case CRUD, gate pass/fail/skip/fail-closed,
and reviewer scoping) and 56 passed + 1 skipped in the agent-only variant. The
web typecheck, lint, seam-check, build and Playwright chat E2E (feedback
button included) pass.
