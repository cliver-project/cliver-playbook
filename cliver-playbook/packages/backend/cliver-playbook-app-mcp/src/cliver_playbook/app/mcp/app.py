"""Self-contained application wrapper for the ``mcp`` package.

``create_app`` assembles the full agent-facing stack: the ``basic`` package's
routers (meta + demo items), the identity package's (auth + admin), the RAG
package's (documents, search, chat, stage discovery), this package's own two
(the ``/mcp`` protocol endpoint and the ``/api/v1/mcp`` views), and the OAuth
2.1 provider surface the protocol endpoint's 401s point agents at. It binds
the process runtime with this package's most-derived Settings instance, so
every package's ``settings`` proxy in the process answers from one
configuration.

No mounted sub-application anywhere: the protocol endpoint is an ordinary route
in an ordinary router (ADR-0017), so assembly is one ``include_router`` loop
over every package's ``ROUTERS`` and the route table shows every route.

Lifespan: the MCP session manager is not a route concern but a process one — it
owns the task group that serves sessions, so it must be running before the
first request and be shut down with the application. ``create_app`` therefore
attaches a lifespan that installs the manager on entry (``install_streamable_app``
is idempotent) and enters ``run()`` for the application's lifetime. Apps built
without this lifespan answer ``/mcp`` with a loud RuntimeError instead of a
half-working endpoint.

One running application per process, by SDK construction: the session manager
may be entered once per instance and the instance belongs to the process
(rebuilding it per app would orphan the tools and the sessions of the first).
Production is one uvicorn process per app. Test suites that boot the app
through ``TestClient`` (whose context manager runs the lifespan) therefore
share a single booted client per process — see ``tests/test_mcp_composition.py``
for the module-scoped pattern.

Importing this module has no side effects: the application exists only once
``create_app`` is called (uvicorn's ``--factory`` convention).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.api.routes import ROUTERS as BASIC_ROUTERS
from cliver_playbook.app.basic.runtime_settings import load_persisted_settings
from cliver_playbook.app.mcp.api.routes import ROUTERS as MCP_ROUTERS
from cliver_playbook.app.mcp.api.streamable import MCP_PATH, install_streamable_app
from cliver_playbook.app.mcp.settings import Settings
from cliver_playbook.app.rag.api.routes import ROUTERS as RAG_ROUTERS
from cliver_playbook.app.user.api.routes import ROUTERS as USER_ROUTERS
from cliver_playbook.app.user.auth.oauth21 import RequestMetaMiddleware, mount_oauth_routes

logger = logging.getLogger("cliver_playbook.app.mcp")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the MCP session manager with the application, stop it with it.

    The manager is installed here rather than at import (no import-time side
    effects — ADR-0016) and entered once for the application's lifetime: it
    holds the task group every session runs in, so its scope is exactly the
    scope of the process serving requests.
    """
    # Operator overrides take effect before the first request. Loading here
    # (rather than at import) keeps package imports side-effect free; a
    # missing table is warned about, not fatal (ADR-0021).
    await load_persisted_settings()
    manager = install_streamable_app()
    async with manager.run():
        logger.info("MCP session manager running at %s", MCP_PATH)
        yield


def configure_runtime(settings: Settings | None = None) -> Settings:
    """Bind the process runtime to this package's Settings and set up logging.

    Two entry points need this: :func:`create_app` and the standalone stdio
    transport (``transport.run_stdio``) — the one entry point that serves MCP
    without assembling an ASGI application, and therefore has to bind the
    database engine and the settings proxies itself.

    Binding is once per process (ADR-0016): a second call with a DIFFERENT
    instance raises, so a process can never end up with two settings worlds or
    two engines.

    Args:
        settings: the instance to bind. Defaults to a fresh ``Settings()``
            (layered resolution relative to the current working directory).

    Returns:
        The bound instance (Settings(), so every package's proxy serves it).
    """
    resolved = settings if settings is not None else Settings()
    runtime.configure(resolved)
    logging.basicConfig(level=resolved.log_level.upper())
    return resolved


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the composed application (dependencies + this package).

    Args:
        settings: the Settings instance to bind to the process runtime.
            Defaults to a fresh ``Settings()`` (layered resolution relative
            to the current working directory). A larger composition passes
            its own — possibly subclassed — instance instead, which every
            module-level ``settings`` proxy in the process then serves.

    Returns:
        The assembled application, ready for uvicorn or an ASGI test client.
    """
    resolved = configure_runtime(settings)
    app = FastAPI(title=resolved.app_name, version="0.1.0", lifespan=_lifespan)

    for router in (*BASIC_ROUTERS, *USER_ROUTERS, *RAG_ROUTERS, *MCP_ROUTERS):
        app.include_router(router)

    # OAuth 2.1 provider surface (agent/API clients). Routes land at the
    # application root because well-known discovery must not carry a prefix.
    app.add_middleware(RequestMetaMiddleware)
    if resolved.oauth21_enabled:
        mount_oauth_routes(app)

    logger.info("Application assembled: %s (MCP endpoint %s)", resolved.app_name, MCP_PATH)
    return app
