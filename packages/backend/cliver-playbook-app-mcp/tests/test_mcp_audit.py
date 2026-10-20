"""The audit wrapper and the concurrency cap around tool execution.

``_call_slot()`` is the semaphore toolkit's wrapper acquires around
every tool body (per process, per event loop). These tests drive it
directly instead of through decorated tools: the contract is "at most
``max_concurrent_calls`` bodies run at once, the rest queue" — peaks
and totals, independent of scheduling order.

Audit-row coverage lives where the rows are produced: the wrapper
contract in ``test_mcp_structural.py``, the rejection rows in
``test_mcp_gate.py``, per-tool success/denial rows in
``test_mcp_tools.py``.
"""

from __future__ import annotations

import asyncio

from cliver_playbook.app.mcp.settings import settings
from cliver_playbook.app.mcp.toolkit import _call_slot


async def _run_probes(count: int) -> tuple[int, int]:
    """Run ``count`` concurrent slot-holding probes.

    Each probe increments a counter inside the slot, yields to the event
    loop (sleep) while holding it, then decrements. Returns
    ``(peak, final)``: the maximum simultaneous occupancy and the
    leftover count, which must be 0 — every acquisition releases.
    """
    current = 0
    peak = 0

    async def probe() -> None:
        nonlocal current, peak
        async with _call_slot():
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.01)
            current -= 1

    await asyncio.gather(*(probe() for _ in range(count)))
    return peak, current


async def test_concurrent_calls_capped(monkeypatch):
    monkeypatch.setattr(settings.mcp, "max_concurrent_calls", 2)
    peak, final = await _run_probes(6)
    assert peak == 2
    assert final == 0


async def test_slot_honours_limit_changes(monkeypatch):
    """The per-loop cache must not pin a stale limit — tightening the
    setting takes effect on the next call (fresh semaphore)."""
    monkeypatch.setattr(settings.mcp, "max_concurrent_calls", 4)
    peak, _ = await _run_probes(4)
    assert peak == 4

    monkeypatch.setattr(settings.mcp, "max_concurrent_calls", 1)
    peak, final = await _run_probes(3)
    assert peak == 1
    assert final == 0
