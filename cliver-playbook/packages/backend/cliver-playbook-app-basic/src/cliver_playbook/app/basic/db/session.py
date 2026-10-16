"""Request-scoped database sessions.

The engine and session factory are created by ``runtime.configure`` — never
at import time — so importing this module in a process that runs no
application (a migration script, a CLI, a docs build) costs nothing.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic import runtime


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session (closed on exit)."""
    factory = runtime.session_factory()
    async with factory() as session:
        yield session


def open_session() -> AsyncSession:
    """Open a session directly on the process runtime's engine.

    ``get_db`` covers the request-scoped dependency case; code that owns its
    own transaction boundaries across several round trips (multi-step auth
    flows, background work, migrations helpers) opens sessions from here
    instead. Both paths resolve the same engine ``runtime.configure`` built,
    so a process never ends up with two connection pools.
    """
    return runtime.session_factory()()
