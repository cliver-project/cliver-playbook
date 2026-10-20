"""mcp: the agent-facing package — an MCP server on top of the identity stack.

Builds on ``user`` (accounts, RBAC, tokens, OAuth 2.1 provider) and contributes
the surface AI agents talk to: the streamable-http protocol endpoint at
``/mcp``, the same server over stdio for locally spawned agents, an auth gate
that resolves agent credentials through the identity package's token table, and
audit rows describing what each agent did.

What this package owns
----------------------

- The ``MCPServer`` instance (``server.py``) plus the tool-registration
  helpers; two built-in tools (``tools/``) that double as examples.
- The transport plumbing (``api/streamable.py``, ``transport.py``,
  ``__main__.py``) for both streamable-http and stdio.
- The auth gate (``auth.py``) — always wrapped around the protocol endpoint; it
  reads ``settings.mcp.auth_enabled`` per request. ON: the request must carry a
  bearer from the identity package's ``auth_tokens`` table, and the gate binds
  the resolved ``Viewer`` to a ContextVar. OFF: an anonymous viewer is bound —
  public tools answer, permission-gated tools deny. The flag never rebuilds
  anything and no build can ship ungated.
- The audit wrapper (``audit.py``) — writes to the same ``audit_logs`` table
  the identity package owns, adding the agent_type / agent_id gathered from the
  request.
- The ``mcp:*`` permission codes (``permissions.py``), registered into the
  identity package's catalog at import.

What this package does NOT own
------------------------------

- Auth tokens (the identity package's ``auth_tokens`` table — there is no
  separate ``mcp_tokens``), the ``Viewer`` dataclass, and the OAuth 2.1
  provider (imported as-is; the protocol endpoint lives at the fixed path its
  protected-resource metadata already advertises).
- Any database tables — this package has no migration chain.

Public surface only; every name below is a plain import (no settings reads, no
engine, no app assembly — importing a package must never have side effects; see
ADR-0015 and ADR-0016).
"""

# Load-bearing import order, not a re-export to tidy up: importing this module
# registers the mcp:* permission codes in the identity package's catalog, and
# every module below that calls require_perm() with one of those codes validates
# against the catalog when IT is imported. Python runs a parent package's
# __init__ before any of its submodules, so this is the one place that
# guarantees the registration happens first (see permissions.py).
from cliver_playbook.app.mcp import permissions  # noqa: F401
from cliver_playbook.app.mcp.api.routes import ROUTERS
from cliver_playbook.app.mcp.app import create_app
from cliver_playbook.app.mcp.settings import Settings, get_settings, settings

__all__ = ["ROUTERS", "Settings", "create_app", "get_settings", "settings"]
