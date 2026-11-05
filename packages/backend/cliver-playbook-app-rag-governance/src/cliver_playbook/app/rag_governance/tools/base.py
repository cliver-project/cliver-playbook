"""Tool contract: the only surface through which a model reaches live data.

Three rules shape this module:

- **Read-only.** A tool that can mutate the ERP is never registered and
  never called. The registry refuses it, and the restricted invoker
  re-checks the flag at call time (defense in depth).
- **Bounded.** Every result carries a row count and a truncation flag,
  and the invoker enforces the tighter of the tool's cap and the
  request's cap.
- **Explicit time.** ``as_of`` is injected by the caller; a tool never
  reads the host clock. That is what makes freshness evaluation
  deterministic and lets a snapshot be labeled with its own cutoff.

``ToolContext`` is a NamedTuple so a caller can derive a child context
with ``_replace`` without rebuilding every field; the composite path
uses that to rebind the restricted registry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """The declarative half of a tool: what a planner may select.

    ``dependencies`` is non-empty only for a composite tool and names
    exactly the vendor tools it may call through the restricted
    invoker. ``result_cap`` is a hard row bound; ``max_staleness_seconds``
    is the age after which a result is too old for a freshness claim.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True
    dependencies: tuple[str, ...] = ()
    result_cap: int = 1000
    max_staleness_seconds: int | None = None


@dataclass(frozen=True)
class ToolCaps:
    """Per-request limits. The effective row bound is the tighter cap."""

    max_rows: int = 1000
    max_bytes: int | None = None
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ToolResult:
    """A normalized tool outcome.

    ``error`` is set when the backend was unreachable or returned an
    unusable payload. That is an explicit "live data unavailable"
    outcome the facade can narrate; it is different from a denied call,
    which raises before reaching the backend.
    """

    tool: str
    data: Any
    as_of: datetime
    row_count: int
    truncated: bool = False
    error: str | None = None


class ToolContext(NamedTuple):
    """Everything a tool may know about the caller and the request.

    The fields are deliberately explicit: no ambient request state, no
    global clock, no database session. ``registry`` is a
    ``RestrictedToolInvoker`` for a composite's declared dependencies;
    a plain tool receives an invoker with an empty allowlist.
    """

    viewer: Any
    access: Any
    project_id: str
    as_of: datetime
    masking: Callable[[Any], Any] | None
    caps: ToolCaps
    registry: Any  # RestrictedToolInvoker | None, forward-declared below
    call_id: str
    parent_call_id: str | None = None
    depth: int = 0


AuditSink = Callable[[dict[str, Any]], Awaitable[None]]


class Tool(Protocol):
    spec: ToolSpec

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class ToolDeniedError(Exception):
    """The call is unauthorized, unbound, recursive, or not read-only."""
