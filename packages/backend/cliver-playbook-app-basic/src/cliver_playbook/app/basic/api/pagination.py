"""FastAPI dependency for the shared limit/offset window.

The bounds are per endpoint (an audit trail and an agent-activity feed do not
need the same maximum), so the dependency is a small factory. Validation
belongs to FastAPI's query parsing: an out-of-range value is a 422, never a
silently clamped request.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Query


@dataclass(frozen=True, slots=True)
class PageParams:
    """A validated limit/offset window, independent of any endpoint."""

    limit: int
    offset: int


def page_params(*, default_limit: int = 50, max_limit: int = 200) -> Callable[..., PageParams]:
    """Return a ``Depends``-able parser for ``?limit=`` and ``?offset=``.

    ``default_limit`` applies when the client omits ``limit``; ``max_limit``
    is the largest window the endpoint accepts. Both are validated here so a
    misconfigured route fails at import time, not on the first request.
    """
    if default_limit < 1:
        raise ValueError("default_limit must be at least 1")
    if max_limit < default_limit:
        raise ValueError("max_limit must be at least default_limit")

    def dependency(
        limit: int = Query(default=default_limit, ge=1, le=max_limit),
        offset: int = Query(default=0, ge=0),
    ) -> PageParams:
        return PageParams(limit=limit, offset=offset)

    return dependency
