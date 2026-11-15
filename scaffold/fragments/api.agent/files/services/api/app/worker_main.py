"""Dedicated agent-run worker entrypoint.

Run the API with ``CLIVER_AGENT_RUN_WORKER_ENABLED=false`` and start this
process instead when HTTP serving and agent execution should scale or fail
independently. The worker shares the API's PostgreSQL database and settings;
it does not run migrations or serve HTTP.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.agents.job_queue import start_job_queue, stop_job_queue
from app.settings import Settings

logger = logging.getLogger(__name__)


async def run_worker(
    settings: Settings | None = None,
    *,
    stop: asyncio.Event | None = None,
) -> None:
    """Start the queue consumer and wait until the stop event or a signal."""
    settings = settings or Settings()
    if not settings.agent_run_worker_enabled:
        raise SystemExit("CLIVER_AGENT_RUN_WORKER_ENABLED must be true in a dedicated worker")
    stop_event = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop is None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)
    await start_job_queue(settings)
    logger.info("agent-run worker started")
    try:
        await stop_event.wait()
    finally:
        await stop_job_queue()
        logger.info("agent-run worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
