# cliver-playbook-app-rag-governance

A reusable governance loop over the `cliver-playbook` RAG stack: one
project per knowledge-base scenario, a golden dataset that gates change,
intent rules that decide retrieval scope and tools, staged ingestion with
an approval gate, and a query facade that enforces document clearance and
tool authority.

The package composes on top of `cliver-playbook-app-rag` and never
replaces it. Documents, chunks, embeddings and retrieval stay owned by
`rag`; this package adds the project-level lifecycle around them.

The financial-metrics / Kingdee scenario under `examples/finance_kpi/` is
the reference integration. It is configuration plus registered composite
tools — not a fork of the package.

Full design: `docs/superpowers/specs/2026-11-05-rag-governance-loop-design.md`
and ADR-0023.
