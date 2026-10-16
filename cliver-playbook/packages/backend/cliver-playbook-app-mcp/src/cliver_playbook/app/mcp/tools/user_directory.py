"""``user_directory`` — the permission-gated tool exemplar.

The shape every real business tool follows:

1. Decorators declare the contract — ``@require_perm(...)`` enforces the
   caller's permissions and writes the audit row, so the function body
   never touches either concern.
2. The body opens its own DB session (tools run outside the request's
   session lifecycle — they may run on stdio or in the standalone
   process, where no HTTP request session exists) and calls the shared
   service layer — never inline table queries, so Web and MCP always
   read the same business rules.
3. The return value is a compact, model-friendly payload: agents pay
   for every token, and internal columns (password hashes, lockout
   state) have no business leaving the service layer anyway.

The gating on BOTH ``mcp:tools:invoke`` and ``user:read`` is deliberate:
the first is the coarse MCP kill-switch (revoke it from a role and no
gated tool works for that role), the second is this tool's data
permission — the same one the Web admin API checks.
"""

from __future__ import annotations

from typing import Any

from cliver_playbook.app.basic.db.session import open_session
from cliver_playbook.app.mcp.server import mcp
from cliver_playbook.app.mcp.toolkit import require_perm
from cliver_playbook.app.user.services.users import list_users

_MIN_LIMIT = 1
_MAX_LIMIT = 200


@mcp.tool()
@require_perm("mcp:tools:invoke", "user:read")
async def user_directory(q: str = "", limit: int = 50) -> dict[str, Any]:
    """Search the user directory by partial username or display name.

    Requires the ``mcp:tools:invoke`` and ``user:read`` permissions.

    Args:
        q: Substring matched against username and display name
            (empty = no filter).
        limit: Maximum number of users to return (1-200, default 50).
    """
    # Clamp instead of rejecting: a model asking for 10_000 rows is
    # over-eager, not malicious — answer with the cap so the call still
    # succeeds and the schema stays simple.
    bounded = max(_MIN_LIMIT, min(int(limit), _MAX_LIMIT))

    async with open_session() as db:
        rows = await list_users(db, q.strip() or None)

    users = [
        {
            "username": row["user"].username,
            "display_name": row["user"].display_name,
            "is_active": row["user"].is_active,
            "roles": row["role_codes"],
        }
        for row in rows[:bounded]
    ]
    return {"count": len(users), "users": users}
