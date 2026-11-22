"""Start the rag-governance job worker with the application lifespan.

Governance endpoints acknowledge asynchronous work with a 202 (ingest,
evaluation, golden generation) and never execute it inline. Without this
worker those jobs stay queued forever, so the module starts one in-process
worker for the process lifetime. `rag_governance.worker_enabled` (default
true) turns it off for a deployment that runs its own worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from cliver_playbook.app.rag_governance.runtime import JOB_HANDLERS, run_worker
from cliver_playbook.app.rag_governance.settings import settings as governance_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def governance_worker() -> AsyncIterator[None]:
    """Run the governance worker inside an already-bound runtime."""
    block = governance_settings.rag_governance
    if not block.worker_enabled:
        logger.info("governance job worker disabled by settings")
        yield
        return

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(stop, JOB_HANDLERS, poll_seconds=block.worker_poll_seconds),
        name="rag-governance-job-worker",
    )
    logger.info("governance job worker started (poll=%.2fs)", block.worker_poll_seconds)
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        logger.info("governance job worker stopped")
