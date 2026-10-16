"""Tool decorators: uniform timing, audit and permission enforcement.

Every tool function registers with exactly one of :func:`public_tool` or
:func:`require_perm` (nested under the SDK's ``@mcp.tool()``). The
decorator is the single place where three cross-cutting concerns happen,
so no tool author can forget one:

- **Timing** — one ``duration_ms`` per call (wall-clock, including any
  queueing behind the concurrency cap), recorded in the audit row.
- **Audit** — exactly one ``mcp.tools.call`` row per call, success or
  failure (see :mod:`cliver_playbook.app.mcp.audit` for the wrapper and its best-effort
  failure policy). The row carries the truncated arguments plus the
  caller identity from the request context, so "who called what, from
  which agent, with which identity" is answerable from one table.
- **Permission enforcement** (:func:`require_perm` only) — the current
  viewer must hold ALL named codes, checked fresh per call. A denial
  raises ``ToolError`` and is audited like any other failure: attempted
  calls without permission are exactly the rows an operator wants to
  see.
- **Concurrency cap** — every tool body executes inside a process-wide
  semaphore (``settings.mcp.max_concurrent_calls``), so a burst of
  agent calls cannot exhaust the DB pool or an upstream API. Queueing,
  not rejection — see :func:`_call_slot`. Denied calls never acquire a
  slot (the permission check runs first).

Error channel: ``ToolError`` is the SDK's "anticipated failure" —
``MCPServer.call_tool`` re-raises it, and the protocol layer turns it
into ``is_error=True`` with the message for the model to read, no
traceback, session alive. Any other exception is a crash the SDK
flattens to a generic client message; we audit it and re-raise so the
bug stays loud in the server logs.

Signature preservation matters here: ``functools.wraps`` keeps
``__wrapped__``, which ``inspect.signature`` follows when the SDK
generates the model-facing input schema — the wrapper's ``**kwargs``
never leaks into the tool contract. A regression test in
``tests/test_mcp_tools.py`` locks this down.

Difference from ``cliver_playbook.app.user.auth.dependencies.require_perm``: that one is a
FastAPI dependency factory for HTTP routes; this one wraps MCP tool
functions. Same idea, different framework seam — hence the same name is
deliberately prefix-free in both home modules.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any
from weakref import WeakKeyDictionary

from cliver_playbook.app.mcp.audit import write_tool_audit
from cliver_playbook.app.mcp.context import current_viewer
from cliver_playbook.app.mcp.settings import settings
from mcp.server.mcpserver.exceptions import ToolError

ToolFn = Callable[..., Awaitable[Any]]

# Per-event-loop semaphores for the concurrency cap. asyncio primitives
# bind to the loop that first awaits them, and one process can run
# several loops over its lifetime (the uvicorn loop, TestClient portals,
# pytest-asyncio per-test loops) — keying by loop keeps them isolated.
# The cached entry carries the limit it was built with, so a settings
# change yields a fresh semaphore instead of one pinned to a stale
# limit (in production the setting only changes at startup anyway).
_slots: WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]] = (
    WeakKeyDictionary()
)


def _call_slot() -> asyncio.Semaphore:
    """The semaphore enforcing ``settings.mcp.max_concurrent_calls``.

    Queueing, not rejection: a burst beyond the cap waits its turn. The
    cap protects downstream resources (DB pool, upstream APIs) — it is
    a backstop, not a rate limiter.
    """
    loop = asyncio.get_running_loop()
    limit = max(1, settings.mcp.max_concurrent_calls)
    entry = _slots.get(loop)
    if entry is None or entry[0] != limit:
        entry = (limit, asyncio.Semaphore(limit))
        _slots[loop] = entry
    return entry[1]


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _describe(exc: Exception) -> str:
    """Compact, predictable error text for the audit row."""
    return f"{type(exc).__name__}: {exc}"


def _enforce(codes: tuple[str, ...], tool_name: str) -> None:
    """Fail closed: every named code must be held by the current viewer.

    ``current_viewer()`` raises RuntimeError when nothing was bound — a
    caller path that bypassed the gate is a wiring bug and must crash
    loudly, not read as a permission denial.
    """
    viewer = current_viewer()
    missing = [code for code in codes if not viewer.has(code)]
    if missing:
        raise ToolError(
            f"Permission denied: tool {tool_name!r} requires "
            f"{', '.join(repr(code) for code in missing)}"
        )


def _audited(fn: ToolFn, codes: tuple[str, ...]) -> ToolFn:
    """Wrap a tool function with permission check + timing + one audit row."""
    tool_name = fn.__name__

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            if codes:
                _enforce(codes, tool_name)
            async with _call_slot():
                result = await fn(*args, **kwargs)
        except Exception as exc:
            await write_tool_audit(
                method="tools/call",
                target=tool_name,
                args=kwargs,
                ok=False,
                error=_describe(exc),
                duration_ms=_elapsed_ms(start),
            )
            raise
        await write_tool_audit(
            method="tools/call",
            target=tool_name,
            args=kwargs,
            ok=True,
            duration_ms=_elapsed_ms(start),
        )
        return result

    return wrapper


def public_tool() -> Callable[[ToolFn], ToolFn]:
    """Mark a tool as callable without any permission (and under auth OFF).

    An explicit, greppable marker on purpose: ``grep -rn "@public_tool"
    app/`` lists every tool exposed to unauthenticated callers, which is
    the list a security review actually wants. Only tools that carry no
    data of their own (probes, echo-style diagnostics) qualify.

    Note the two orthogonal switches: auth ON/OFF decides *whether the
    gate demands a token at all*; public vs ``require_perm`` decides
    *what the resolved viewer must hold*. A public tool under auth ON is
    still only reachable with a valid token — it just doesn't check the
    viewer's permissions once the token resolves.
    """

    def decorate(fn: ToolFn) -> ToolFn:
        return _audited(fn, ())

    return decorate


def require_perm(*codes: str) -> Callable[[ToolFn], ToolFn]:
    """Gate a tool on ALL of ``codes`` held by the current viewer (AND).

    AND semantics are the safe default: a tool touching one domain
    should name that domain's permissions explicitly
    (``@require_perm("mcp:tools:invoke", "user:read")``). The generic
    ``mcp:tools:invoke`` code doubles as a coarse kill-switch — revoking
    it from a role disables every gated tool for that role without
    touching data permissions.

    Raises ValueError at decoration time on an empty code list — that's
    a tool-authoring bug (meant ``@public_tool()``), caught at import,
    not per call.
    """
    unique = tuple(dict.fromkeys(codes))
    if not unique:
        raise ValueError(
            "require_perm needs at least one permission code — "
            "use @public_tool() for intentionally ungated tools"
        )

    def decorate(fn: ToolFn) -> ToolFn:
        return _audited(fn, unique)

    return decorate
