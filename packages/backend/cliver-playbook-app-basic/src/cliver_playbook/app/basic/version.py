"""Application version metadata.

The release tooling keeps every distribution on one version; reading it from
installed metadata means an app factory never carries a version string that
drifts from its manifest. A source copy that has no distribution metadata
still boots, reporting ``0.0.0``.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def package_version(distribution: str) -> str:
    """Return ``distribution``'s installed version, or ``0.0.0`` if absent."""
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "0.0.0"
