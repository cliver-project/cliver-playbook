"""Self-contained application wrapper for the governance package.

A product build includes ``ROUTERS`` in its own app (ADR-0015/0017);
this factory exists so the package can run and be tested on its own.
The runtime is bound with this package's most-derived Settings, which
every package's ``settings`` proxy then serves (ADR-0016).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.api.routes import ROUTERS as BASIC_ROUTERS
from cliver_playbook.app.basic.runtime_settings import settings_lifespan
from cliver_playbook.app.basic.version import package_version
from cliver_playbook.app.rag.api.routes import ROUTERS as RAG_ROUTERS
from cliver_playbook.app.rag_governance.api.routes import ROUTERS as GOVERNANCE_ROUTERS
from cliver_playbook.app.rag_governance.query.facade import RuleToolPlanner
from cliver_playbook.app.rag_governance.settings import Settings
from cliver_playbook.app.rag_governance.tools import ToolRegistry
from cliver_playbook.app.user.api.routes import ROUTERS as USER_ROUTERS
from cliver_playbook.app.user.auth.oauth21 import RequestMetaMiddleware, mount_oauth_routes

logger = logging.getLogger("cliver_playbook.app.rag_governance")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the governance application (dependencies + this package)."""
    resolved = settings if settings is not None else Settings()
    runtime.configure(resolved)

    logging.basicConfig(level=resolved.log_level.upper())
    app = FastAPI(
        title=resolved.app_name,
        version=package_version("cliver-playbook-app-rag-governance"),
        lifespan=settings_lifespan,
    )
    # The query facade's tool seam. A scenario registers its composite
    # tools on this registry at composition time; core governance
    # registers none.
    app.state.tool_registry = ToolRegistry()
    app.state.tool_planner = RuleToolPlanner()

    for router in (*BASIC_ROUTERS, *USER_ROUTERS, *RAG_ROUTERS, *GOVERNANCE_ROUTERS):
        app.include_router(router)

    app.add_middleware(RequestMetaMiddleware)
    if resolved.oauth21_enabled:
        mount_oauth_routes(app)

    logger.info("Application assembled: %s", resolved.app_name)
    return app
