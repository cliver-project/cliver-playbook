"""Self-contained application wrapper for the ``user`` package.

``create_app`` assembles the full identity stack: the ``basic`` package's
routers first (meta + demo items), then this package's own (auth + admin),
then the OAuth 2.1 provider surface for agent clients. It binds the process
runtime with this package's most-derived Settings instance, so every
package's ``settings`` proxy in the process answers from one configuration.

Unit of work: identity routers commit once per request at the end (service
mutations + audit row together); the basic package's items service commits
itself. Both patterns coexist fine — each request touches one style.

Importing this module has no side effects: the application exists only once
``create_app`` is called (uvicorn's ``--factory`` convention).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.api.routes import ROUTERS as BASIC_ROUTERS
from cliver_playbook.app.basic.runtime_settings import settings_lifespan
from cliver_playbook.app.user.api.routes import ROUTERS as USER_ROUTERS
from cliver_playbook.app.user.auth.oauth21 import RequestMetaMiddleware, mount_oauth_routes
from cliver_playbook.app.user.settings import Settings

logger = logging.getLogger("cliver_playbook.app.user")


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
    resolved = settings if settings is not None else Settings()
    runtime.configure(resolved)

    logging.basicConfig(level=resolved.log_level.upper())
    app = FastAPI(title=resolved.app_name, version="0.1.0", lifespan=settings_lifespan)

    for router in (*BASIC_ROUTERS, *USER_ROUTERS):
        app.include_router(router)

    # OAuth 2.1 provider surface (agent/API clients). Routes land at the
    # application root because well-known discovery must not carry a prefix.
    app.add_middleware(RequestMetaMiddleware)
    if resolved.oauth21_enabled:
        mount_oauth_routes(app)

    logger.info("Application assembled: %s", resolved.app_name)
    return app
