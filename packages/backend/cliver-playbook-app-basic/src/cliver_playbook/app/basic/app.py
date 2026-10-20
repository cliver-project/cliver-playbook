"""Self-contained application wrapper for the ``basic`` package.

``create_app`` binds the process runtime (settings instance + database
engine) and assembles a FastAPI application from this package's ROUTERS —
the same composition a consumer project performs, so the standalone entry
point and a composed application can never drift apart.

Importing this module has no side effects: the application exists only once
``create_app`` is called (uvicorn's ``--factory`` convention).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.api.routes import ROUTERS
from cliver_playbook.app.basic.runtime_settings import settings_lifespan
from cliver_playbook.app.basic.settings import Settings

logger = logging.getLogger("cliver_playbook.app.basic")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble this package's standalone FastAPI application.

    Args:
        settings: the Settings instance to bind to the process runtime.
            Defaults to a fresh ``Settings()`` (layered resolution relative
            to the current working directory). A composed application passes
            its own — possibly subclassed — instance instead, which every
            module-level ``settings`` proxy in the process then serves.

    Returns:
        The assembled application, ready for uvicorn or an ASGI test client.
    """
    resolved = settings if settings is not None else Settings()
    runtime.configure(resolved)

    logging.basicConfig(level=resolved.log_level.upper())
    app = FastAPI(title=resolved.app_name, version="0.1.0", lifespan=settings_lifespan)
    for router in ROUTERS:
        app.include_router(router)

    logger.info("Application assembled: %s", resolved.app_name)
    return app
