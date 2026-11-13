# cliver-playbook-app-rag-governance (frontend)

The governance loop as pages: a loop overview, intent rules with a live
matcher, sources and ingestion batches, the staged-preview approval gate,
golden sets (import / generate / confirm / fork), evaluation runs with
per-case verdicts, and the governed query facade with its observation panel.

Composes with the identity package's session chrome:

```tsx
import { govNavItems, govRoutes, govTranslations } from "cliver-playbook-app-rag-governance";
```

The dev shell (`dev/`) builds the demo app — basic + user + this package —
with the `/api` proxy pointed at the standalone governance backend on
`127.0.0.1:18000` (see the backend package's README, "Local demo"). Pages
gate themselves with `RequirePerm` on the same `rag_governance:*` codes the
server enforces; structured documents (rule sets, golden JSONL) are edited
as JSON on purpose — the server schema is the contract, not a parallel form.
