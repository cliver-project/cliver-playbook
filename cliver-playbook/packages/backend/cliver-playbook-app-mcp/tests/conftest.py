"""Shared test fixtures: an isolated temp PostgreSQL database per test session.

Design (mirrors the playbook conftest contract):
- Connect to CLIVER_TEST_DATABASE_URL (admin DSN, default = the compose `db`
  service) and CREATE DATABASE cliver_mcp_test_<pid>; drop it on session end.
- Point CLIVER_DATABASE_URL at the temp database BEFORE constructing Settings:
  the environment layer outranks every config file, so the settings stack can
  never hijack the temp database.
- Pin CLIVER_CONFIG_FILE at this package's fixture app.yaml: the surrounding
  checkout's app.yaml is not this package's business, and the transport tests
  spawn subprocesses that inherit this environment.
- Bind the process through ``create_app`` (the real assembly path) and apply
  both dependency migration chains in order — ``basic`` first, then ``user``,
  whose foreign keys point at basic's tables. This package owns no tables and
  no chain, so those two are the whole schema.
- autouse `reset_database`: TRUNCATE every table between tests. Milliseconds
  fast; the engine is disposed first because asyncpg connections are bound to
  the event loop that created them.
- If PostgreSQL is unreachable, skip the whole session with a hint instead of
  producing a wall of connection errors.
"""

import atexit
import os
from pathlib import Path

import psycopg
import pytest

ADMIN_DSN = os.environ.get(
    "CLIVER_TEST_DATABASE_URL", "postgresql://cliver:cliver@127.0.0.1:5432/postgres"
)
TEST_DB_NAME = f"cliver_mcp_test_{os.getpid()}"
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
        f"PostgreSQL unavailable ({exc.__class__.__name__}) — is the compose db running?",
        allow_module_level=True,
    )

# Environment beats every config layer: point the application at the temp
# database before any Settings instance is constructed.
os.environ["CLIVER_DATABASE_URL"] = TEST_DSN

from cliver_playbook.app.basic.config_yaml import CONFIG_FILE_ENV_VAR

# Pin the YAML layer (see module docstring) — before the first Settings().
os.environ[CONFIG_FILE_ENV_VAR] = str(Path(__file__).parent / "fixtures" / "app.yaml")

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.alembic import run_migrations_online as run_basic_migrations
from cliver_playbook.app.mcp.app import create_app
from cliver_playbook.app.mcp.settings import Settings
from cliver_playbook.app.user.alembic import run_migrations_online as run_user_migrations

settings = Settings()
# The application under test, assembled once for the process: binding the
# runtime is a once-per-process operation (ADR-0016), so tests take this
# instance through the `app` fixture rather than building their own.
_app = create_app(settings)
run_basic_migrations()  # dependency chain first...
run_user_migrations()  # ...then the identity tables this package's tools read
atexit.register(_drop_temp_database)


@pytest.fixture(scope="session")
def app():
    """The composed application under test (see module docstring)."""
    return _app


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
    """ASGI HTTP client bound to the application — no network, no server.

    Note what this does NOT do: it never runs the lifespan, so the MCP session
    manager is not running. That is enough for every route except a real MCP
    call — the gate answers rejections before the endpoint is reached, which is
    why the gate's HTTP tests use this fixture. A request that does reach the
    endpoint without the lifespan fails loudly by design (see
    ``api/streamable.py``); tests that need a served endpoint boot the app with
    ``TestClient`` instead (``test_mcp_composition.py``).
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
async def db():
    """Direct session for seeding/asserting behind the API's back."""
    from cliver_playbook.app.basic.db.session import open_session

    async with open_session() as session:
        yield session


@pytest.fixture
async def admin_headers(client, db):
    """Seeded admin (all permissions), logged in through the real endpoint."""
    from .helpers import TEST_ADMIN_PASSWORD, login, seed_admin

    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {token}"}
