# The governance loop, for the agent

A governed knowledge base is not just "documents plus a model". The loop that
makes an answer trustworthy:

1. **Semantics** — intent rules map a question to a strategy: retrieval only,
   live tools, an agentic plan, or a refusal. Rules are versioned and only an
   active version answers.
2. **Ingestion is staged** — new documents enter as staged rows, invisible to
   queries until an approval publishes them. A batch without an evaluation
   report cannot be approved.
3. **The golden set gates change** — a confirmed, immutable set of cases with
   expected intent, strategy, sources and numeric facts. An evaluation run
   replays it; a passing run is required before rules activate.
4. **Answers carry their trace** — intent, strategy, rule version, citations
   with locators, tool calls with as-of and row counts.

What this means for you as the agent:

- **Never claim data is live when the trace says snapshot.** `is_snapshot`
  and `period` on a tool call are part of the answer.
- **Never answer from the corpus when the strategy was `none`.** A refusal is
  the system working as designed.
- **Never suggest publishing, approving or activating on the user's behalf**
  from this skill. Those are separate human actions with their own
  permissions; the connector is read-only.
