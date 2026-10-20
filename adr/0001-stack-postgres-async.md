# ADR-0001: PostgreSQL-only backend with async SQLAlchemy

**Status:** Accepted (2026-10-15)
**Context:** cliver-playbook service scaffold — the base every template builds on.

## Decision

1. **PostgreSQL only** (16, provided by docker compose in every template). No SQLite
   dev-mode, no dual-dialect discipline. JSONB, TIMESTAMPTZ, and identity columns are
   used freely.
2. **Async SQLAlchemy 2.0 + asyncpg** for the application runtime. This follows the
   CraftForge lineage (async engine, `async_sessionmaker`, `get_db` dependency) rather
   than the ai-gov-agent lineage (sync sessions throughout).
3. **Alembic migrations run on the sync psycopg driver** with a `sync_db_url` derived
   from the same canonical `CLIVER_DATABASE_URL`. The two drivers never share an engine.
4. **The app refuses to start without `CLIVER_DATABASE_URL`** — a clear startup error
   beats a cryptic failure inside the first query.
5. Python 3.12+, uv for environments/locks, `package = false` (app, not a library).

## Consequences

- Every async path must stay async: blocking CPU work (notably PBKDF2 hashing in the
  user-management template) is wrapped in `asyncio.to_thread`.
- Tests create a temp database per session and `TRUNCATE` between tests (asyncpg
  connections are loop-bound; the pool is disposed between tests — see conftest).
- Alembic autogenerate diffs work because `target_metadata` is the app's `Base`.

## Alternatives considered

- **Sync SQLAlchemy** (ai-gov-agent style): simpler mental model, but the reference
  scaffold (CraftForge) and the wider FastAPI ecosystem have settled on async; picking
  sync would force a rewrite of the session/dependency patterns when borrowing from
  either. Chosen owner: LG — see plan record.
- **SQLite default with optional PG**: rejected — dual-dialect support forbids JSONB
  and forces portable-by-least-common-denominator types; PG-only keeps templates
  honest and matches every real deployment.
