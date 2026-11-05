"""The governance routers compose with the RAG routers without collisions.

A product application includes every package's ``ROUTERS`` list in one
FastAPI app (ADR-0015). FastAPI dispatches on method plus path and accepts a
duplicate silently, so a collision would shadow a route instead of failing
loudly. The same path with different methods is normal (``GET`` and ``POST``
on a collection, ``GET`` and ``PATCH`` on a resource); the guard is on the
``(method, path)`` pair.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter

from cliver_playbook.app.rag.api.routes import ROUTERS as RAG_ROUTERS
from cliver_playbook.app.rag_governance import ROUTERS as GOVERNANCE_ROUTERS


def _routes(routers: Iterable[APIRouter]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for router in routers:
        for route in router.routes:
            for method in sorted(getattr(route, "methods", ()) or ()):
                pairs.append((method, route.path))
    return pairs


def test_governance_routers_compose_without_duplicate_paths() -> None:
    pairs = _routes((*RAG_ROUTERS, *GOVERNANCE_ROUTERS))

    duplicates = sorted({pair for pair in pairs if pairs.count(pair) > 1})
    assert not duplicates, f"duplicate method/path routes across packages: {duplicates}"


def test_each_package_registers_its_own_paths() -> None:
    rag_paths = {path for _, path in _routes(RAG_ROUTERS)}
    governance_paths = {path for _, path in _routes(GOVERNANCE_ROUTERS)}

    assert rag_paths
    assert governance_paths
    assert not rag_paths & governance_paths
