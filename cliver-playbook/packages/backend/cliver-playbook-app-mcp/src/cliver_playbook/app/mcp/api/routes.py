"""Router contract: the list of ``APIRouter``s this package contributes.

A composed application includes every package's ``ROUTERS`` list directly::

    for router in [*basic.ROUTERS, *user.ROUTERS, *mcp.ROUTERS]:
        app.include_router(router)

Each router carries its own unique path prefix, so the lists compose without
collisions. Cross-package composition never mounts sub-applications: importing
a package must not build an app, and a mounted sub-app hides its routes from
the parent's route table (ADR-0015, ADR-0017).

The protocol endpoint carried by ``streamable.router`` is the case that used to
justify a mount. It is an ``APIRouter`` like the others because FastAPI's
router inclusion copies plain Starlette routes across (rebuilding them from
``route.endpoint``), so one include loop reaches every route this package
contributes — including ``/mcp``.
"""

from fastapi import APIRouter

from cliver_playbook.app.mcp.api import discovery, streamable

# List order is the include order; the two path prefixes are disjoint.
ROUTERS: list[APIRouter] = [streamable.router, discovery.router]
