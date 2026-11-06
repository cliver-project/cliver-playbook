# Add backend permission codes

## Use when

A project route, service, navigation entry, or MCP tool needs a new
`resource:action` permission. Register the code before using it.

Profile: `web`, `rag`, or `mcp`.

## Do

### 1. Register the code at import time

```python
# app/permissions.py
from cliver_playbook.app.user.auth.permissions import (
    Permission,
    register_permission_codes,
)

register_permission_codes(
    [
        Permission("orders:read", "View orders", "Orders"),
        Permission("orders:write", "Create and edit orders", "Orders"),
    ]
)
```

`Permission(code, description, group)` is the catalog entry. The group is the
admin UI's pick-list heading.

### 2. Make the import order explicit

```python
# app/__init__.py
"""Project package. The import order is load-bearing."""

from app import permissions  # noqa: F401 — before any router imports
```

Do the same at the top of `migrate.py`, before the identity chain seeds roles.
The live catalog is validated when `require_perm(...)` is evaluated at module
import; a missing registration is an import error, not a silent 403.

### 3. Guard the route at module scope

```python
from fastapi import Security

from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

_READ = Security(require_perm("orders:read"))
_WRITE = Security(require_perm("orders:write"))
```

Build the dependency once. A typo then fails when the module imports instead
of on the first request.

### 4. Assign the code to roles

The seeded `admin` role holds the `*` wildcard. Assign project codes to other
roles through **Admin → Roles**, or in the project's own seed. A role that
lacks the code receives 403 from the server; hiding a nav item is not
authorization.

## Verify

```sh
uv run python -c "
from app import permissions
from cliver_playbook.app.user.auth.permissions import permission_codes
print(sorted(permission_codes()))
"
uv run pytest
```

The catalog must contain the new code exactly once. Then call the guarded
endpoint as a viewer with and without the role assignment.

## Pitfalls

- Registering the same code twice with different metadata raises at import.
- Reusing a package-owned prefix (`settings:*`, `user:*`, `role:*`,
  `audit:*`, `oauth:*`, `rag:*`, `mcp:*`) collides with the package catalog.
  Use the project's own resource name.
- `require_perm` on an MCP tool is AND across every code; name the tool gate
  (`mcp:tools:invoke`) plus the domain code deliberately.
- `RequirePerm` in the frontend is only an affordance. The server-side code is
  the enforcement point.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/auth/permissions.py`
  — `Permission`, `register_permission_codes`, `permission_catalog`.
- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/auth/dependencies.py`
  — `require_perm`.
- Worked example: the identity package registers its own codes in the same
  catalog at import.
- Deep dive: `reference/decision-guide.md` section "Project permission codes".
