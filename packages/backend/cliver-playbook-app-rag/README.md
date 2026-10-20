# cliver-playbook-app-rag

Knowledge-base package of the cliver-playbook library: document ingestion,
pluggable chunking, embeddings, retrieval, reranking, and grounded chat over
the identity stack.

## What is inside

| Area | Path (under `src/cliver_playbook/app/rag/`) | Notes |
|---|---|---|
| API | `api/` | Document upload/list/delete, stage catalog, search and chat routers. |
| Chunking | `chunking/` | Format-specific, configurable chunkers (recursive, markdown, code, DOCX, HTML, PDF). See `chunking/README.md` and ADR-0019. |
| Embedding | `embedding/` | BGE-M3 and BGE-base-zh stages through cliver-core local providers; remote providers via cliver-core. |
| Retrieval | `retrieval/` | Vector search, BM25 fallback, and hybrid retrieval. |
| Reranking | `reranking/` | BGE reranker through cliver-core, or a remote rerank provider. |
| LLM | `llm/` | Chat generation through cliver-core purpose bindings (ADR-0020, ADR-0022). |
| Settings | `settings.py`, `settings_section.py` | Module-owned settings, exposed through the runtime settings framework (ADR-0021). |
| Migrations | `alembic/` | Own chain, version table `alembic_version_rag`; enables pgvector. |

The package composes with `cliver-playbook-app-user` (and therefore
`cliver-playbook-app-basic`); it does not ship its own identity surface.

## Install

```bash
python -m pip install cliver-playbook-app-rag
```

The local BGE stages need the cliver-core local extra, which this package
already declares. The base install stays torch-free; model weights download on
first use unless they are already cached.

## Test

```bash
python -m pytest        # needs PostgreSQL; creates and drops a temp database
```
