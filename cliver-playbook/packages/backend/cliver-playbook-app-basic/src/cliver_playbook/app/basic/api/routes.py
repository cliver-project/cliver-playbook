"""Router contract: the list of ``APIRouter``s this package contributes.

A composed application includes every package's ``ROUTERS`` list directly::

    for router in [*basic.ROUTERS, *user.ROUTERS, *mcp.ROUTERS]:
        app.include_router(router)

Each router carries its own unique path prefix, so the lists compose without
collisions. Cross-package composition never mounts sub-applications:
importing a package must not build an app, and a mounted sub-app hides its
routes from the parent's route table (ADR-0015).
"""

from fastapi import APIRouter

from cliver_playbook.app.basic.api import items, meta

# List order is the include order; keep routers with more specific prefixes
# ahead of broader ones if prefixes ever overlap.
ROUTERS: list[APIRouter] = [meta.router, items.router]
