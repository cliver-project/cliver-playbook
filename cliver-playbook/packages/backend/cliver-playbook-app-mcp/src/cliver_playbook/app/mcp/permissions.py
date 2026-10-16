"""The ``mcp:*`` permission codes, registered into the shared catalog.

The catalog itself (and the no-``permissions``-table rule) belongs to the
identity package: it is the only component that can enforce a code, because
only it resolves a viewer's roles and permissions per request. This package
contributes its four codes through ``register_permission_codes()`` — the
extension seam designed for composing packages (ADR-0017) — at import time,
so that by the time anything here calls ``require_perm("mcp:...")`` the code
already exists in the live catalog.

Why registration instead of editing the identity package's catalog literal:
a deployment that installs only the identity package must not ship four codes
nobody can ever satisfy (they would show up in the admin UI's pick-list as
bindable, grant nothing, and need a migration every time a composing package
changed its surface). Registration is in-memory and import-driven, so the
catalog matches the code that is actually present in the process: admin
pick-list, role-binding validation and the migration seed all read the merged
view, and a composed deployment seeds these four onto the admin role with no
extra step.

Import order matters — a ``require_perm()`` call site validates against the
catalog when its own module is imported, so the codes must already be there.
The ordering is guaranteed by construction rather than by callers remembering:
this package's ``__init__`` imports this module before any other submodule, and
Python always executes a package's ``__init__`` before any of its submodules,
so no import path into this package can reach a call site first. Removing that
first import from ``__init__`` breaks the guarantee — it is not a re-export to
tidy up.
"""

from __future__ import annotations

from cliver_playbook.app.user.auth.permissions import Permission, register_permission_codes

# Owned by this package. Order is presentation order in the admin UI pick-list.
MCP_PERMISSIONS: tuple[Permission, ...] = (
    Permission("mcp:tools:invoke", "Invoke MCP tools", "MCP"),
    Permission("mcp:prompts:get", "Read MCP prompts", "MCP"),
    Permission("mcp:resources:read", "Read MCP resources", "MCP"),
    # Operator view of what agents do: the audit rows written by the tool
    # wrappers and the gate rejections. Deliberately a separate grant from
    # `audit:read` — watching agent traffic and reading the identity audit
    # trail are different jobs (see cliver_playbook/app/mcp/api/discovery.py).
    Permission("mcp:agents:read", "View MCP agent activity", "MCP"),
)

# Registering on import is the intended pattern (see module docstring).
# register_permission_codes() is idempotent for identical entries, so a
# re-import — or two modules importing this one — is a no-op, while a
# *conflicting* redefinition elsewhere still fails loudly.
register_permission_codes(MCP_PERMISSIONS)

# Plain code strings, for callers that only need the identifiers (the gate's
# documentation, tests asserting the seed granted them to the admin role).
MCP_PERMISSION_CODES: tuple[str, ...] = tuple(p.code for p in MCP_PERMISSIONS)
