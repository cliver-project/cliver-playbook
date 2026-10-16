"""Router contract: the list of ``APIRouter``s this package contributes.

A composed application includes every package's ``ROUTERS`` list directly::

    for router in [*basic.ROUTERS, *user.ROUTERS, *mcp.ROUTERS]:
        app.include_router(router)

Each router carries its own unique path prefix, so the lists compose without
collisions. Cross-package composition never mounts sub-applications:
importing a package must not build an app, and a mounted sub-app hides its
routes from the parent's route table (ADR-0015).

Note: this package's OAuth 2.1 provider surface (``/.well-known/*``, token,
registration and revocation endpoints) does NOT appear here. Those routes are
created by the MCP SDK at call time and are added by ``create_app`` via
``auth.oauth21.mount_oauth_routes`` — they live at the application root, which
an APIRouter's static prefix cannot express.
"""

from fastapi import APIRouter

from cliver_playbook.app.user.api import admin, auth

# List order is the include order; the two prefixes are disjoint.
ROUTERS: list[APIRouter] = [auth.router, admin.router]
