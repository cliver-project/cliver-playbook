# cliver-app

A production-shaped service scaffold: **FastAPI + async SQLAlchemy + PostgreSQL** backend,
**React 19 + Vite + Tailwind CSS v4 + shadcn/ui** frontend, with i18n (English/中文),
light/dark theming, migrations, and tests — all green out of the box.

## Stack

| Layer     | Choice |
|-----------|--------|
| Backend   | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async, asyncpg), Alembic, uv |
| Database  | PostgreSQL 16 via docker compose (dev + test) |
| Frontend  | React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui (vendored), pnpm |
| HTTP/data | axios (interceptors), TanStack Query, React Router |
| i18n      | i18next + react-i18next (`src/locales/`), en + zh bundled |
| Theming   | CSS variables driven by `data-theme` (light/dark/system), no-flash boot |
| Quality   | pytest (temp PostgreSQL per session), ruff, oxlint, `tsc -b` |

## Quickstart

```bash
make init                   # backend (uv) + frontend (pnpm) dependencies
make backend-start          # starts db container, migrates, serves http://127.0.0.1:8000
make web-ui-start           # serves http://127.0.0.1:5173 (proxies /api to :8000)
# No .env needed for local development — defaults match the bundled compose
# db. Copy .env.example to .env only to override (e.g. another database).
```

Verify:

```bash
curl http://127.0.0.1:8000/api/v1/health     # {"status":"ok"}
make backend-test                            # 9 tests against a temp PostgreSQL DB
pnpm --dir frontend build                    # type-check + production build
```

## Layout

```
backend/
  app/core/config.py     # pydantic-settings; CLIVER_ prefix; dual DB URLs (async/sync)
  app/db/                # async engine, session factory, get_db dependency
  app/models/entities.py # ORM entities (demo: Item)
  app/schemas/           # Pydantic request/response contracts
  app/services/          # persistence rules (transport-agnostic)
  app/api/               # routers: meta (health/version), items (demo CRUD)
  alembic/               # migration chain (0001_scaffold_base is the root)
  tests/                 # conftest: temp PG database per session, TRUNCATE per test
frontend/
  src/api/client.ts      # axios instance + bearer-token hook
  src/api/items.ts       # typed wrappers for one entity — the API-module pattern
  src/i18n/              # i18next bootstrap (detection: localStorage -> navigator)
  src/locales/{en,zh}.json
  src/components/ui/     # vendored shadcn/ui primitives (zero network at bootstrap)
  src/components/theme/  # ThemeProvider (light/dark/system) + toggle
  src/components/crud/   # useCrudQueries (list+mutations+toasts) + DataTable
  src/layouts/           # AppLayout: header, nav, language + theme controls
  src/pages/ItemsPage.tsx # reference entity-CRUD page — copy for new entities
```

## Conventions

- **Python package stays `app`** — it is never renamed (ADR-0002). Project renaming
  touches three tokens only: `cliver_app` (ids), `cliver-app` (display), `CLIVER_` (env).
- One canonical `CLIVER_DATABASE_URL`; the app derives the asyncpg and psycopg DSNs.
- UI copy always goes through `t()`; add keys to both `en.json` and `zh.json`.
- New entities: model in `entities.py`, schemas, service, router, then
  `uv run alembic revision --autogenerate -m "..."`.
- New entity CRUD page (frontend): copy `src/pages/ItemsPage.tsx`, swap the
  API module (`src/api/items.ts` is the pattern), form fields, columns and
  i18n keys — `components/crud/` supplies the query/mutation/toast plumbing
  and the table states. Add route + nav + locale keys.
- Tests need PostgreSQL (`make db-up`); without it the suite skips with a hint.
