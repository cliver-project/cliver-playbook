"""Shared test fixtures: an isolated temp PostgreSQL database per test session.

Design (mirrors the playbook conftest contract):
- Connect to CLIVER_TEST_DATABASE_URL (admin DSN, default = the compose `db`
  service) and CREATE DATABASE cliver_app_test_<pid>; drop it on session end.
- Point CLIVER_DATABASE_URL at the temp database BEFORE importing `app` — the
  engine binds at import time, so env must be settled first.
- Run `alembic upgrade head` once per session (the real migration chain —
  schema drift between migrations and models fails loudly here).
- autouse `reset_database`: TRUNCATE every table between tests. Milliseconds
  fast, and keeps the import-time engine untouched.
- If PostgreSQL is unreachable, skip the whole session with a hint instead of
  producing a wall of connection errors.
"""

import atexit
import os

import psycopg
import pytest

ADMIN_DSN = os.environ.get(
    "CLIVER_TEST_DATABASE_URL", "postgresql://cliver:cliver@127.0.0.1:5432/postgres"
)
TEST_DB_NAME = f"cliver_app_test_{os.getpid()}"
TEST_DSN = f"postgresql://cliver:cliver@127.0.0.1:5432/{TEST_DB_NAME}"


def _create_temp_database() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        # Idempotent for repeated runs in the same process (e.g. pytest re-entry).
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


def _drop_temp_database() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')


try:
    _create_temp_database()
except Exception as exc:  # noqa: BLE001 — any failure means "no database, no tests"
    pytest.skip(
        f"PostgreSQL unavailable ({exc.__class__.__name__}) — run `make db-up` first",
        allow_module_level=True,
    )

# Engine binds at import time: settle the env before importing anything under `app`.
os.environ["CLIVER_DATABASE_URL"] = TEST_DSN

from alembic.config import Config

from alembic import command
from app.db.session import engine
from app.main import app

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_migrations() -> None:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")


_run_migrations()
atexit.register(_drop_temp_database)


@pytest.fixture(autouse=True)
async def reset_database() -> None:
    """Truncate every table between tests.

    asyncpg connections are bound to the event loop that created them, and
    pytest-asyncio runs each test on a fresh function-scoped loop — so the
    pool must be disposed between tests, letting each test reconnect on its
    own loop. Tables are discovered dynamically: later templates add tables
    without touching this fixture.
    """
    from sqlalchemy import text

    await engine.dispose()
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = [r[0] for r in rows if not r[0].startswith("alembic")]
        if tables:
            table_list = ", ".join(f'"{t}"' for t in sorted(tables))
            await conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
            await conn.commit()


@pytest.fixture
async def client():
    """ASGI HTTP client bound to the application — no network, no server."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


# ===========================================================================
# user-management fixtures
# ===========================================================================


@pytest.fixture
async def db():
    """Direct session for seeding/asserting behind the API's back."""
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def admin_headers(client, db):
    """Seeded admin (all permissions), logged in through the real endpoint."""
    from tests.helpers import TEST_ADMIN_PASSWORD, login, seed_admin

    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {token}"}
