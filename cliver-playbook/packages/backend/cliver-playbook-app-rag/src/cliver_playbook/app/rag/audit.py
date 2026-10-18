"""RAG-side audit wrapper: thin layer over user-management's ``write_audit``.

Every RAG operation lands one row in the existing ``audit_logs`` table
the identity package owns. The RAG delta on top of UM's row is the
``event`` name (``rag.document.upload`` / ``rag.document.index`` /
``rag.search.run`` / ``rag.chat.run``) and the stage metadata (chosen
chunker / embedder, hit count, the configured retriever) inside the
``detail`` JSONB column. No ``ALTER TABLE`` (R7 / ADR-0014) — the
schema stays the identity package's, only the event names and the
``detail`` shape are new.

Failure policy: a ``write_audit`` that raises is logged at WARNING
and swallowed. The operation's own success/failure is the primary
record; audit is best-effort, matching the mcp package's audit
wrapper and the ai-gov lineage that justifies the policy (a transient
DB hiccup must not break an otherwise-successful upload).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cliver_playbook.app.rag.audit")


async def write_rag_audit(
    *,
    event: str,
    target: str,
    ok: bool,
    args: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write one audit row for a RAG operation. Best-effort; never raises.

    Args:
        event: the action verb; will be prefixed with ``rag.`` in the
            audit row. Examples: ``document.upload``, ``document.index``,
            ``search.run``, ``chat.run``.
        target: the document id, query hash, or operation target that
            the row is about. A short opaque string.
        ok: True when the operation succeeded, False when it failed.
        args: optional dict of operation-specific arguments (e.g. the
            chosen chunker / embedder ids). Goes into the ``detail``
            column's ``args`` key.
        extra: optional dict merged into ``detail`` alongside ``args``
            (for caller-specific fields like ``hits_used`` or
            ``no_hits``).
    """
    try:
        from cliver_playbook.app.basic.db.session import open_session
        from cliver_playbook.app.user.auth.audit import write_audit

        detail: dict[str, Any] = {"args": args or {}}
        if extra:
            detail.update(extra)
        async with open_session() as session:
            await write_audit(
                session=session,
                event=f"rag.{event}",
                target=target,
                ok=ok,
                detail=detail,
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag audit write failed for event=%s: %s", event, exc)
