"""Router contract: the list of ``APIRouter``s this package contributes.

A composed application includes every package's ``ROUTERS`` list directly::

    for router in [*basic.ROUTERS, *user.ROUTERS, *rag.ROUTERS, *mcp.ROUTERS]:
        app.include_router(router)

Each router carries its own unique path prefix, so the lists compose
without collisions. Cross-package composition never mounts sub-
applications: importing a package must not build an app, and a mounted
sub-app hides its routes from the parent's route table (ADR-0015,
ADR-0017).

Importing this module imports each route module, which is what builds
the routers. The side effect is deliberate and bounded: route modules
declare endpoints and resolve their permission codes against the live
catalog, but never touch the database, build an application, or read
configuration.
"""

from __future__ import annotations

from fastapi import APIRouter

from cliver_playbook.app.rag.api import documents

# Search and chat routers join this list in their own implementation
# tasks; the composed application picks them up automatically.
ROUTERS: list[APIRouter] = [documents.router]
