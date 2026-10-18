"""Router contract: the list of ``APIRouter``s this package contributes.

A composed application includes every package's ``ROUTERS`` list directly::

    for router in [*basic.ROUTERS, *user.ROUTERS, *rag.ROUTERS, *mcp.ROUTERS]:
        app.include_router(router)

Each router carries its own unique path prefix, so the lists compose
without collisions. Cross-package composition never mounts sub-
applications: importing a package must not build an app, and a mounted
sub-app hides its routes from the parent's route table (ADR-0015,
ADR-0017). The RAG package's routers are populated in their
implementation tasks; this list starts empty so the package can be
imported before any router is built.
"""

from __future__ import annotations

from fastapi import APIRouter

# Populated by the api/documents.py, api/search.py, api/chat.py
# modules as those tasks land. Importing this module has no side
# effects beyond building the list reference; the routers themselves
# are registered when those submodules are imported (which happens
# when a composed application loads the API surface).
ROUTERS: list[APIRouter] = []
