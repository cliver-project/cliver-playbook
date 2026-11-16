# Connector tool contracts

The connector points at the application's MCP endpoint (streamable HTTP). The
server must expose these three tools. Field names are the contract; the
governance package's query facade is the source of truth for the response
shape (`packages/backend/cliver-playbook-app-rag-governance/.../query/`).

> Distribution status: this package is the client-side contract. The demo MCP
> server currently ships `echo` and `user_directory` only; the governance
> tools below are added to the app's MCP surface through the toolkit seam
> (`@mcp.tool()` + `@public_tool()` / `@require_perm(...)`). Until they exist,
> a call fails with "unknown tool" — report that as a connector setup problem,
> not as an answer.

## `governed_kb_list_projects`

No arguments.

```json
{"items": [{"id": "uuid", "slug": "finance-kpi", "name": "Finance KPI", "status": "active"}]}
```

## `governed_kb_project_status`

Arguments: `project` (id or slug).

```json
{
  "project": "finance-kpi",
  "status": "active",
  "active_rule_version": 2,
  "pending_batches": 0,
  "confirmed_golden_version": 1
}
```

`status` is one of `draft`, `baseline_eval`, `active`, `paused`, `archived`.
Only `active` with a non-null `active_rule_version` can answer questions.

## `governed_kb_ask`

Arguments:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `project` | string | yes | Project id or slug. |
| `question` | string | yes | The user's question, verbatim. |
| `as_of` | ISO-8601 string | no | Reference time for period questions. |

Response (the query facade's `QueryResponse`, trimmed):

```json
{
  "text": "…",
  "intent": "receivables_aging",
  "strategy": "agentic",
  "citations": [{"kind": "document", "ref": "ar-aging-policy", "locator": "预警阈值", "as_of": null}],
  "tool_calls": [{"name": "finance_receivables_aging", "args_fingerprint": "…", "as_of": "2026-10-31T23:59:59+08:00", "row_count": 4, "latency_ms": 12, "error": null, "is_snapshot": false, "period": "2026-10"}],
  "as_of": "2026-10-31T23:59:59+08:00",
  "refused": false,
  "rule_version": 2
}
```

A `refused: true` response is a policy outcome. Explain it; do not retry with
a different phrasing.
