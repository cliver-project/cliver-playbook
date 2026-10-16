"""Time helpers.

All timestamps in the identity domain are timezone-aware UTC. Centralizing
`utcnow()` avoids the classic bug where one module compares a naive datetime
against a TIMESTAMPTZ column read and raises `TypeError: can't compare
offset-naive and offset-aware datetimes`.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time, timezone-aware."""
    return datetime.now(UTC)
