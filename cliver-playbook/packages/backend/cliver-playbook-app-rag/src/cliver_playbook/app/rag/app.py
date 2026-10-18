"""Self-contained application wrapper for the ``rag`` package.

``create_app`` assembles the packages RAG depends on (``basic`` and the
identity package ``user``) plus this package's own routers, exactly the
way the ``user`` package assembles basic + itself. A larger composition
(the mcp package, or a product build) never calls this function: it
imports ``rag.api.routes.ROUTERS`` and includes them in its own app
(ADR-0015 / ADR-0017). This one exists so the package can run and be
tested on its own.

The process runtime is bound here with this package's most-derived
Settings instance (which subclasses the identity package's), matching
the pattern of every other package (ADR-0016). Importing this module
has no side effects; uvicorn's ``--factory`` convention implies that.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.api.routes import ROUTERS as BASIC_ROUTERS
from cliver_playbook.app.rag.api.routes import ROUTERS as RAG_ROUTERS
from cliver_playbook.app.rag.settings import Settings
from cliver_playbook.app.user.api.routes import ROUTERS as USER_ROUTERS
from cliver_playbook.app.user.auth.oauth21 import RequestMetaMiddleware, mount_oauth_routes

logger = logging.getLogger("cliver_playbook.app.rag")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the RAG application (dependencies + this package).

    Args:
        settings: the Settings instance to bind to the process runtime.
            Defaults to a fresh ``Settings()`` (layered resolution
            relative to the current working directory). A larger
            composition passes its own — possibly subclassed — instance
            instead, which every module-level ``settings`` proxy in the
            process then serves.

    Returns:
        The assembled application, ready for uvicorn or an ASGI test
        client.
    """
    resolved = settings if settings is not None else Settings()
    runtime.configure(resolved)

    logging.basicConfig(level=resolved.log_level.upper())
    app = FastAPI(title=resolved.app_name, version="0.1.0")

    for router in (*BASIC_ROUTERS, *USER_ROUTERS, *RAG_ROUTERS):
        app.include_router(router)

    # The identity package's request metadata middleware stamps every
    # audit row with the caller's IP / user agent. RAG writes audit rows
    # through the same table, so it needs the same stamping.
    app.add_middleware(RequestMetaMiddleware)
    if resolved.oauth21_enabled:
        mount_oauth_routes(app)

    logger.info("Application assembled: %s", resolved.app_name)
    return app
