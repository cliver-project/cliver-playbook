# cliver-playbook

A personal engineering asset library for a one-person company: composable backend and
frontend packages that a new project assembles, plus the architecture decisions behind
them. A new service starts as "install or copy the packages a project needs, wire three
things, write the first feature" — instead of re-deriving auth, migrations, i18n and
the MCP surface on every project.

The library used to be three copy-based templates (scaffold, user management, MCP
server) with copy manifests between them. It is now packages: one place per concern,
no physical duplicates, no drift (ADR-0015). The template tree and its `INTEGRATION.md`
manifests are gone; nothing below depends on them.

## Packages

Backend — Python, one distribution each, importing as `cliver_playbook.app.<name>`
(PEP 420 namespace, so any subset installs into one environment):

| Package | Owns |
| --- | --- |
| `packages/backend/cliver-playbook-app-basic` | Settings/runtime (ADR-0016), the async engine and session factory, the demo `items` table and its CRUD endpoints, the first migration chain. No business dependencies. |
| `packages/backend/cliver-playbook-app-user` | The identity domain (ADR-0003/0004/0005): users/roles/permissions, password login with lockout and must-change-password, multi-provider OIDC login, the OAuth 2.1 authorization server for agent clients, linked accounts, the unified audit log, and the admin API. |
| `packages/backend/cliver-playbook-app-rag` | The knowledge base (ADR-0018): pluggable chunking, embedding, retrieval, reranking and LLM stages with per-request selection, upload/index/search/chat endpoints, pgvector storage with a lexical fallback, and stage discovery for the UI. |
| `packages/backend/cliver-playbook-app-mcp` | The MCP surface (ADR-0014/0017): the streamable-http endpoint as an ordinary router route with a permission gate, stdio transport, permission-enforced example tools, agent identity and call audit, and the aggregate `migrate` entry point. |

Frontend — React 19 + Vite, source-only packages (ADR-0008): the app's build
transpiles them, so there is no `dist` and no build step per package.

| Package | Owns |
| --- | --- |
| `packages/frontend/cliver-playbook-app-basic` | The visual shell: theme provider and tokens, i18n bootstrap, the axios client, the UI primitive set, the CRUD/table pattern, the layout, the home/items pages, and the shared tooling (vite/tsconfig/index.html) an app extends. |
| `packages/frontend/cliver-playbook-app-user` | Sign-in and the password gate, the session provider and client policy, the profile page, the RBAC admin pages, the standalone OAuth pages. |
| `packages/frontend/cliver-playbook-app-mcp` | The tool playground and the agent activity view. |

Each frontend package has a `dev/` shell — a real app that consumes the packages by
name. The `cliver-playbook-app-mcp` shell is the full composition (basic + user + mcp)
and doubles as the reference for what a finished project's wiring looks like.

## Consuming the library

Two supported models, both composing the same way:

- **Install**: `python -m pip install -e ../cliver-playbook-app-basic` (and `-e` the
  others, dependencies first) into the project's virtualenv, or resolve them through a
  uv workspace; `workspace:*` on the pnpm side. Packages stay live, fixes land once.
- **Copy**: copy the chosen packages' sources into the project and drop the dependency
  on this repository. A self-contained project, at the cost of picking up later changes
  by hand.

Wiring a composed app is deliberately small — there is no per-project glue code to
maintain:

```python
for router in [*basic.ROUTERS, *user.ROUTERS, *rag.ROUTERS, *mcp.ROUTERS]:
    app.include_router(router)          # no Mount, prefixes are the packages' own
```

```tsx
const routes: RouteObject[] = [
  { element: <AuthAppLayout extraNavItems={mcpNavItems} />,
    children: [...basicRoutes, ...userRoutes, ...mcpRoutes] },
  ...userStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];
createI18n(userTranslations, mcpTranslations);
```

The Claude Code skills that automate the assembly (choose packages → copy or install →
wire) are the next work item; until they land, the models above are the documented
path, and the mcp frontend shell is the worked example to copy from.

## Running this repository

```sh
make db-up          # PostgreSQL in docker (the only containerised piece)
make init           # uv sync + pnpm install
make db-init        # apply every package's migration chain, dependencies first
make backend-start  # the composed app on http://127.0.0.1:8000
make web-ui-start   # the composed frontend shell on http://127.0.0.1:5173
make check          # ruff + every package's tests + the frontend typecheck/lint/build
```

`make mcp-stdio` / `make mcp-http` run the MCP surface as a separate process for a
local CLI agent or a sidecar listener. `.env.example` documents every override;
`app.yaml` (checked in, never carries secrets) is the lowest-priority layer (ADR-0009).

## Architecture decisions

`adr/` holds the "why" behind every structural choice, including when a decision stops
applying — read before deviating:

- 0001 PostgreSQL-only + async SQLAlchemy; dual driver URLs
- 0002 Fixed `app` package name, three-token rename surface — *superseded by 0015*
- 0003 RBAC tables and the code-defined permission catalog
- 0004 One `auth_tokens` table, three token kinds, predicate discipline
- 0005 The identity domain owns both OAuth directions
- 0006 MCP sub-app mounting and lifespan composition — *superseded by 0017*
- 0007 Copy-merge template model — never written; retired by 0015
- 0008 Frontend platform and libraries (incl. source-only packages)
- 0009 Layered configuration with a checked-in `app.yaml`
- 0014 MCP auth ON/OFF, agent identity, shared token table
- 0015 Composable packages and router composition
- 0016 Extensible settings and the process runtime
- 0017 The MCP endpoint is an ordinary router route
- 0018 RAG as a composable package with pluggable stages

## Conventions

- Everything is English-only and domain-neutral. **No client names, project names, real
  URLs or credentials ever enter this repository** — examples use placeholders.
- Secrets live in the gitignored `.env`; the repository ships only `.env.example`.
- Commits are conventional, one step each, with the tests for that step green.
- ADRs are append-only: a decision that is replaced gets a `Superseded by` banner, never
  an edit — the history of why something changed is the part worth keeping.
