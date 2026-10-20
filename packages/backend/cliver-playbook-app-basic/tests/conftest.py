"""Shared test fixtures: an isolated temp PostgreSQL database per test session.

Design (mirrors the playbook conftest contract):
- Connect to CLIVER_TEST_DATABASE_URL (admin DSN, default = the compose `db`
  service) and CREATE DATABASE cliver_basic_test_<pid>; drop it on session end.
- Point CLIVER_DATABASE_URL at the temp database BEFORE constructing Settings:
  the environment layer outranks every config file, so the settings stack can
  never hijack the temp database.
- Bind the process through ``create_app`` (the real assembly path) and apply
  this package's migration chain via ``run_migrations_online()`` — the same
  entry point a new project calls, so the tests exercise real initialization.
- autouse `reset_database`: TRUNCATE every table between tests. Milliseconds
  fast; the engine is disposed first because asyncpg connections are bound to
  the event loop that created them.
- If PostgreSQL is unreachable, skip the whole session with a hint instead of
  producing a wall of connection errors.
"""

import atexit
import os

import psycopg
import pytest

from .dsn import derive_test_dsn

ADMIN_DSN = os.environ.get(
    "CLIVER_TEST_DATABASE_URL", "postgresql://cliver:cliver@127.0.0.1:5432/postgres"
)
TEST_DB_NAME = f"cliver_basic_test_{os.getpid()}"
TEST_DSN = derive_test_dsn(ADMIN_DSN, TEST_DB_NAME)


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
        f"PostgreSQL unavailable ({exc.__class__.__name__}) — is the compose db running?",
        allow_module_level=True,
    )

# Environment beats every config layer: point the application at the temp
# database before any Settings instance is constructed.
os.environ["CLIVER_DATABASE_URL"] = TEST_DSN

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.alembic import run_migrations_online
from cliver_playbook.app.basic.app import create_app
from cliver_playbook.app.basic.settings import Settings

settings = Settings()
app = create_app(settings)  # binds the process runtime (settings + engine)
run_migrations_online()  # migrates the temp database through the runtime settings
atexit.register(_drop_temp_database)


@pytest.fixture(autouse=True)
async def reset_database() -> None:
    """Truncate every table between tests (see module docstring).

    Tables are discovered dynamically: composed applications add tables
    without touching this fixture, while the ``alembic*`` version tables are
    left alone.
    """
    from sqlalchemy import text

    engine = runtime.engine()
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
