---
name: governed-kb
description: Answer business questions from a governed knowledge base. Use when the user asks about company policy, finance metrics, approvals, or any question that must be grounded in approved, access-controlled documents and live tools — and when the user asks whether a knowledge base project is ready to answer questions.
license: Apache-2.0
metadata:
  author: cliver-project
  version: "0.1.0"
---

# Governed knowledge base

This skill turns a question into a governed query. The connector exposes the
governance MCP tools; this skill decides which tool to call, in what order,
and what to do with a refusal. The rules are not style advice — a governed
knowledge base that gets bypassed is worse than no knowledge base at all.

## Use when

- The user asks a business question that should be answered from the
  company's approved corpus (policies, metric definitions, reports) and from
  live read-only tools (ERP metrics, receivables aging).
- The user asks about governance state: which project is active, whether a
  batch is waiting for approval, or which rule version answered a question.
- The user asks for the evidence behind an answer: citations, tool calls,
  the reference time.

Do not use this skill for general knowledge questions, for writing code, or
for answering from your own prior knowledge — if the governed project has no
evidence, say so.

## Do

1. **List the projects.** Call `governed_kb_list_projects`. If several
   projects exist, show name, slug and status and ask which one; never guess.
2. **Check the project is ready.** Call `governed_kb_project_status` with the
   chosen project. If the status is not `active` or there is no active rule
   version, explain the governance loop in one short paragraph (staged data →
   evaluation gate → approval → active rules) and stop. Never pretend the
   project can answer, and never suggest bypassing the gate.
3. **Ask the governed question.** Call `governed_kb_ask` with the project,
   the user's question verbatim, and `as_of` when the question is about a
   period (use the period the user named; if they named none and the demo
   corpus is period-pinned, ask once which period they mean).
4. **Present the trace.** Answer in the user's language, then show:
   intent and strategy, the rule version, the citations (document id and
   locator), the tool calls (name, rows, period, as-of) and the reference
   time. If `refused` is true, report the refusal reason verbatim and stop.
5. **Never fabricate evidence.** Every number in the answer must come from a
   tool call or a citation. If the trace has neither, say the governed
   project has no evidence for the question.

## Verify

- The answer's numbers appear in `tool_calls` results or in cited documents.
- `as_of` in the response matches the period the user asked about (or the
  default the project pins).
- A refusal is reported as a refusal, not rephrased into an answer.
- Governance state questions are answered from tool output, not from memory.

## Pitfalls

- **Asking without a project.** `governed_kb_ask` requires a project; a
  status of `draft` means the loop has not finished, not that it is broken.
- **Re-asking to get past a refusal.** A `refused` response is the policy
  working. Rephrasing to evade it is a governance bypass.
- **Inventing `as_of`.** Use the period from the question; the demo corpus is
  pinned to a closed period, and the host clock is never the reference time.
- **Summarizing away citations.** The value of the trace is that the user can
  check it; keep document ids and locators.

## Source of truth

- Tool contracts: `references/tools.md`
- The governance loop and its guardrails: `references/governance-loop.md`
