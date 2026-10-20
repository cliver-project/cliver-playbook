# Backend composition

The backend is a FastAPI application assembled from the selected playbook
packages plus a project-owned domain package. Every step below is a seam the
playbook supports; nothing here edits an installed package.

## Layout

```text
pyproject.toml
uv.lock
alembic.ini
app/
  __init__.py            # imports app.permissions first
  settings.py            # Settings subclass of the most-derived package
  settings_section.py    # optional project runtime-settings section
  permissions.py         # project permission codes
  app.py                 # create_app(): the only runtime binding
  db.py                  # project-owned declarative Base
  migrate.py             # every chain, dependency order, then the project's
  models/
  schemas/
  services/
  api/
    __init__.py          # ROUTERS = [...]
    orders.py
  tools/                 # only for the mcp profile
    __init__.py
    orders.py
  migrations/
    __init__.py          # programmatic run_migrations_online
    env.py
    script.py.mako
    versions/
tests/
  conftest.py
```

## Dependencies

Pin every selected package explicitly, at the same tag. List them in
dependency order for readability (`basic` → `user` → `rag` → `mcp`).

```toml
[project]
name = "example-app"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "cliver-playbook-app-basic==0.1.0",
    "cliver-playbook-app-user==0.1.0",
    "cliver-playbook-app-rag==0.1.0",
    "cliver-playbook-app-mcp==0.1.0",
    # Direct imports in this project. Declaring them keeps the project's
    # requirements explicit instead of relying on transitive resolution.
    "fastapi>=0.143.0",
    "uvicorn[standard]>=0.35.0",
    "sqlalchemy>=2.0.36",
    "alembic>=1.16.0",
    "pydantic-settings>=2.16,<3",
    "psycopg[binary]>=3.2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "anyio>=4.4.0",
    "httpx>=0.28.0",
    "ruff>=0.8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
ignore = ["B008"]  # FastAPI Depends(...) in defaults is the framework idiom

[tool.ruff.lint.isort]
known-first-party = ["app", "cliver_playbook"]
```

Only the packages for the chosen profile appear in `dependencies`:
`minimal` → basic; `web` → basic, user; `rag` → basic, user, rag; `mcp` → all
four. `uv add "cliver-playbook-app-user==0.1.0"` is equivalent; pin the
version explicitly rather than accepting a range.

## Settings

Subclass the most-derived package for the profile. Do not define a parallel
`Settings` class: the runtime binds exactly one instance, and every package's
`settings` proxy serves it.

```python
# app/settings.py
from cliver_playbook.app.mcp.settings import Settings as PlaybookSettings


class Settings(PlaybookSettings):
    """Project settings. Every playbook block is inherited unchanged."""

    feature_orders_enabled: bool = True
```

| Profile | Import base |
|---|---|
| `minimal` | `cliver_playbook.app.basic.settings.Settings` |
| `web` | `cliver_playbook.app.user.settings.Settings` |
| `rag` | `cliver_playbook.app.rag.settings.Settings` |
| `mcp` | `cliver_playbook.app.mcp.settings.Settings` |

The project fields participate in the same layers: construction kwargs >
`CLIVER_*` environment > project `.env` > runtime overrides > `app.yaml`
(bare field names) > defaults.

## Permission codes and import order

`require_perm()` validates its code against the live catalog **when the
router module is imported**. A project router that calls
`require_perm("orders:read")` therefore fails at import unless the code was
registered first.

```python
# app/permissions.py
from cliver_playbook.app.user.auth.permissions import (
    Permission,
    register_permission_codes,
)

register_permission_codes(
    [
        Permission("orders:read", "View orders", "Orders"),
        Permission("orders:write", "Create and edit orders", "Orders"),
    ]
)
```

```python
# app/__init__.py
"""Project package. The import order below is load-bearing."""

from app import permissions  # noqa: F401 — before any router imports
```

Importing the project package now always registers its codes first. Keep the
same guarantee in `migrate.py`, which must import `app.permissions` before the
identity chain seeds roles.

For the `minimal` profile there is no identity package; omit
`app/permissions.py` and every permission argument.

## The application factory

This is the `mcp` profile. Remove the imports and the lines named for
packages the project does not use; the per-profile table follows.

```python
# app/app.py
"""The one place the process runtime is bound and the app is assembled."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import permissions  # noqa: F401 — permission codes before routers
from app import tools  # noqa: F401 — registers project MCP tools
from app.api.routes import ROUTERS as PROJECT_ROUTERS
from app.settings import Settings
from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.api.routes import ROUTERS as BASIC_ROUTERS
from cliver_playbook.app.basic.runtime_settings import settings_lifespan
from cliver_playbook.app.mcp.api.routes import ROUTERS as MCP_ROUTERS
from cliver_playbook.app.mcp.api.streamable import install_streamable_app
from cliver_playbook.app.rag.api.routes import ROUTERS as RAG_ROUTERS
from cliver_playbook.app.user.api.routes import ROUTERS as USER_ROUTERS
from cliver_playbook.app.user.auth.oauth21 import (
    RequestMetaMiddleware,
    mount_oauth_routes,
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the MCP session manager for the application's lifetime.

    ``settings_lifespan`` must wrap it: it applies persisted runtime settings
    before the first request and disposes the engine after the manager stops.
    """
    async with settings_lifespan(app):
        manager = install_streamable_app()
        async with manager.run():
            yield


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    runtime.configure(resolved)
    logging.basicConfig(level=resolved.log_level.upper())

    app = FastAPI(title=resolved.app_name, version="0.1.0", lifespan=_lifespan)
    for router in (
        *BASIC_ROUTERS,
        *USER_ROUTERS,
        *RAG_ROUTERS,
        *MCP_ROUTERS,
        *PROJECT_ROUTERS,
    ):
        app.include_router(router)

    app.add_middleware(RequestMetaMiddleware)
    if resolved.oauth21_enabled:
        mount_oauth_routes(app)
    return app
```

Rules that are not optional:

- **No `FastAPI.mount()`.** Every package exposes `ROUTERS`; include them.
- **`runtime.configure()` runs once**, from `create_app`, before anything
  reads settings or opens a session.
- **`RequestMetaMiddleware`** comes from the identity package and stamps audit
  rows with the caller's IP and user agent. Profiles `web`, `rag`, and `mcp`
  need it because they write audit rows.
- **`mount_oauth_routes(app)`** is guarded by `resolved.oauth21_enabled`; the
  routes belong at the application root because `/.well-known/*` cannot carry
  an API prefix.
- **The MCP session manager is entered in the lifespan**, never at import.
  A missing lifespan answers `/mcp` with a `RuntimeError` instead of
  half-working.

Per profile:

| Profile | Routers | Middleware / OAuth | Lifespan |
|---|---|---|---|
| `minimal` | `BASIC_ROUTERS`, project | none | `settings_lifespan` |
| `web` | `BASIC_ROUTERS`, `USER_ROUTERS`, project | `RequestMetaMiddleware`; guarded `mount_oauth_routes` | `settings_lifespan` |
| `rag` | + `RAG_ROUTERS` | same as web | `settings_lifespan` |
| `mcp` | + `MCP_ROUTERS` | same as web | wrapped with `install_streamable_app()` |

## Project routers

```python
# app/api/routes.py
from app.api.orders import router as orders_router

ROUTERS = [orders_router]
```

```python
# app/api/orders.py
from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.orders import OrderRead
from app.services import orders as orders_service
from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

_READ = Security(require_perm("orders:read"))
_WRITE = Security(require_perm("orders:write"))


@router.get("", response_model=list[OrderRead])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> list[OrderRead]:
    return await orders_service.list_orders(db)
```

Build `Security(require_perm(...))` once at module scope: the validation then
runs at import, where a typo is loud, instead of on every request.

## Project migration chain

The project owns a chain with its own version table. Never add revisions to a
playbook package's directory, and never reuse their version tables.

```python
# app/db.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-owned metadata: autogenerate sees only the project's tables."""
```

```python
# app/migrations/__init__.py
from pathlib import Path

from alembic import command
from alembic.config import Config

_SCRIPT_LOCATION = Path(__file__).resolve().parent


def run_migrations_online(database_url: str | None = None) -> None:
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
```

```python
# app/migrations/env.py
from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base
from app.models import orders  # noqa: F401 — table definitions
from app.settings import Settings

VERSION_TABLE = "alembic_version_app"

config = context.config


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    return url if url else Settings().sync_db_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

The final dispatch is load-bearing: `env.py` is executed as a script, so
without it Alembic defines the functions and exits, reporting success while
creating nothing.

`alembic.ini` (copy the logging sections from a playbook package's file):

```ini
[alembic]
script_location = app/migrations
file_template = %%(rev)s_%%(slug)s
path_separator = os
# sqlalchemy.url is resolved in env.py from Settings.sync_db_url.
```

`script.py.mako` can be copied from
`packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/alembic/script.py.mako`.

The aggregate runner applies every chain in dependency order, then the
project's:

```python
# app/migrate.py
"""Apply every migration chain in dependency order, then the project's."""

from app import permissions  # noqa: F401 — project codes before the role seed
from app.migrations import run_migrations_online as run_project
from app.settings import Settings
from cliver_playbook.app.basic.alembic import run_migrations_online as run_basic
from cliver_playbook.app.rag.alembic import run_migrations_online as run_rag
from cliver_playbook.app.user.alembic import run_migrations_online as run_user


def main() -> None:
    url = Settings().sync_db_url
    for run in (run_basic, run_user, run_rag):
        run(url)
    run_project(url)


if __name__ == "__main__":
    main()
```

For `minimal`, remove the user/rag imports and calls. For `web`, remove rag.
For `mcp`, keep all three: the mcp package owns no chain of its own. Pass the
sync DSN explicitly so the migration process does not need the runtime
configured and never opens the async engine.

### Foreign keys to playbook tables

Use a project-owned `Base` and **do not declare database foreign keys to
`users` or other playbook tables**. Store the id (for example `user_id`) as a
plain indexed `BigInteger` and enforce existence and deletion rules in the
service layer. This keeps autogenerate scoped to the project's tables, which
is the same design the playbook uses for `app_settings.updated_by`.

If a database-level foreign key is genuinely required, the project must share
the playbook's base (`cliver_playbook.app.basic.db.base.Base`) and import the
identity entities in `env.py`; autogenerate then sees the whole basic + user
metadata and is safe only when those chains are already applied. Record that
tradeoff as a decision; it is not the default.

## Domain slice

A minimal but complete pattern:

```python
# app/models/orders.py
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    total_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

```python
# app/services/orders.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orders import Order


async def list_orders(db: AsyncSession, *, limit: int = 100) -> list[Order]:
    result = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(min(limit, 500))
    )
    return list(result.scalars())
```

```python
# app/models/__init__.py
from app.models import orders  # noqa: F401 — imported by Alembic env.py
```

Pick one transaction style and keep it: the service commits (the basic
package's items service does) or the router commits once per request (the
identity routers do). Do not mix both in one request path.

Generate the first revision after the backend imports cleanly:

```sh
uv run alembic revision --autogenerate -m "orders"
uv run alembic upgrade head
```

Review the generated revision: autogenerate is a draft, not a migration.
Constraints, indexes, server defaults, and data backfills are the project's
responsibility. The project chain must remain applicable to an empty database
and idempotent under `upgrade head`.

## MCP tools (mcp profile only)

```python
# app/tools/orders.py
from typing import Any

from cliver_playbook.app.mcp.server import mcp
from cliver_playbook.app.mcp.toolkit import require_perm

from app.services.orders import list_orders


@mcp.tool()
@require_perm("mcp:tools:invoke", "orders:read")
async def list_recent_orders(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent orders visible to the caller."""
    rows = await list_orders(limit=limit)
    return [
        {"id": row.id, "status": row.status, "total_cents": row.total_cents}
        for row in rows
    ]
```

```python
# app/tools/__init__.py
from app.tools import orders  # noqa: F401 — registers the tool
```

Import `app.tools` at the top of `app/app.py`. The decorator writes the audit
row, enforces the permissions, applies the concurrency cap, and records the
duration; a bare `@mcp.tool()` without one of the toolkit decorators is
invisible in the audit trail. Use `@public_tool()` only for diagnostics that
carry no data.

The built-in `echo` and `user_directory` tools remain registered. They are
examples, not the project's tool set.

## Tests

Adapt the playbook's `tests/conftest.py` pattern. The important parts:

```python
import atexit
import os
from pathlib import Path

import psycopg
import pytest

# Use the same credentials as the project's docker-compose.yml. Keep them in
# `.env` or CI variables; the literals below are placeholders.
ADMIN_DSN = os.environ.get(
    "CLIVER_TEST_DATABASE_URL",
    "postgresql://<user>:<password>@127.0.0.1:5432/postgres",
)
TEST_DB_NAME = f"example_app_test_{os.getpid()}"
TEST_DSN = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


def _create_temp_database() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


def _drop_temp_database() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')


try:
    _create_temp_database()
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PostgreSQL unavailable: {exc}", allow_module_level=True)

os.environ["CLIVER_DATABASE_URL"] = TEST_DSN
os.environ["CLIVER_CONFIG_FILE"] = str(Path(__file__).parent / "fixtures" / "app.yaml")

from app.app import create_app
from app.migrations import run_migrations_online as run_project
from app.settings import Settings
from cliver_playbook.app.basic.alembic import run_migrations_online as run_basic
from cliver_playbook.app.rag.alembic import run_migrations_online as run_rag
from cliver_playbook.app.user.alembic import run_migrations_online as run_user

settings = Settings()
app = create_app(settings)
run_basic()
run_user()
run_rag()
run_project()
atexit.register(_drop_temp_database)
```

- Point `CLIVER_DATABASE_URL` at the temp database **before** constructing
  `Settings`: the environment layer outranks every file.
- Pin `CLIVER_CONFIG_FILE` at a fixture `app.yaml` so the suite does not
  inherit the checkout's configuration.
- Apply the chains in dependency order, exactly as `migrate.py` does.
- Truncate every non-`alembic*` table between tests; discover them from
  `pg_tables` so new tables need no fixture edit.
- Provide `client` (httpx `ASGITransport`), `db` (`open_session`), and an
  `admin_headers` fixture that seeds the admin and logs in through the real
  endpoint. The package tests under `var/playbook/packages/backend/*/tests/`
  are the reference for the seed and login helpers.

## Makefile

```make
.DEFAULT_GOAL := help

BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
WEB_UI_PORT ?= 5173

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  %-18s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: init
init: ## Install backend and frontend dependencies
	uv sync
	pnpm install

.PHONY: db-up
db-up: ## Start PostgreSQL
	docker compose up -d db

.PHONY: db-init
db-init: db-up ## Apply every migration chain, dependencies first
	uv run python -m app.migrate

.PHONY: backend-start
backend-start: db-init ## Run the API with auto-reload
	uv run uvicorn --factory app.app:create_app --reload \
		--host $(BACKEND_HOST) --port $(BACKEND_PORT)

.PHONY: web-start
web-start: ## Run the frontend dev server
	pnpm dev --host 127.0.0.1 --port $(WEB_UI_PORT)

.PHONY: migrate
migrate: ## Apply only the project's own chain
	uv run alembic upgrade head

.PHONY: lint
lint: ## Backend format and import checks
	uv run ruff check
	uv run ruff format --check

.PHONY: test
test: db-up ## Backend tests against a scratch database
	uv run pytest

.PHONY: web-check
web-check: ## Type-check, lint and build the frontend
	pnpm typecheck
	pnpm lint
	pnpm build

.PHONY: check
check: lint test web-check ## Everything CI runs
```

Use `python3` for the playbook's own scripts (`assemble_project.py`,
`validate_project_manifest.py`) when `uv run` would resolve them against the
project's environment; they are stdlib-only except the manifest validator,
which needs PyYAML.
