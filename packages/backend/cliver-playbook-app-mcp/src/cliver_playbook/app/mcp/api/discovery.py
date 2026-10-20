"""MCP discovery endpoint for the Web UI (read-only, unauthenticated).

The playground page needs two facts it must not hardcode: the public path the
MCP surface answers on and whether the auth gate is on (the page warns loudly
when anyone reaching the port can call tools). Both facts are already
discoverable by anything that can open a socket — a bare POST to the endpoint
answers 401 or a JSON-RPC frame either way — so this endpoint adds no exposure,
and it stays dependency-free so a signed-out visitor (a future login-page
banner, an operator's curl) can read it.

The path is reported from the same constant the route is built with, so the
answer cannot drift from the wire even though the value is fixed rather than
configured (ADR-0017).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.mcp.api.streamable import MCP_PATH
from cliver_playbook.app.mcp.server import SERVER_NAME
from cliver_playbook.app.mcp.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm
from cliver_playbook.app.user.models.entities import AuditLog
from cliver_playbook.app.user.schemas.auth import AuditLogPage, AuditLogRead

# Static prefix: a mounted-package deployment's API surface lives at exactly
# this path (the prefix is not configurable — ADR-0016).
router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get("/info")
async def mcp_info() -> dict:
    """Public facts about the MCP surface: where it lives, who may call it."""
    return {
        "server_name": SERVER_NAME,
        "path": MCP_PATH,
        "auth_enabled": settings.mcp.auth_enabled,
    }


@router.get("/calls", response_model=AuditLogPage)
async def list_mcp_calls(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _viewer: Viewer = Depends(require_perm("mcp:agents:read")),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    """Recent MCP activity: tool calls plus gate rejections, newest first.

    Deliberately NOT a filter over the generic ``/admin/audit`` endpoint —
    that one requires ``audit:read``, which the MCP-operator role should
    not need. Watching what agents do (``mcp:agents:read``) and reading
    the identity audit trail (``audit:read``) are different grants, and
    the ``event LIKE 'mcp.%'`` predicate is enforced here server-side so
    neither permission can read the other's rows through this route.
    Gate rejections are included on purpose: failed authentication
    attempts are part of "what happened at the MCP boundary".
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.event.like("mcp.%"))
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = select(func.count()).select_from(AuditLog).where(AuditLog.event.like("mcp.%"))
    rows = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return AuditLogPage(
        items=[AuditLogRead.model_validate(row) for row in rows.scalars().all()],
        total=int(total or 0),
    )
