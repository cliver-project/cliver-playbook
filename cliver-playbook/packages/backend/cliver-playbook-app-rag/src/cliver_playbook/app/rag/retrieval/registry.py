"""Retriever registry."""

from __future__ import annotations

from collections.abc import Callable

from cliver_playbook.app.rag.retrieval.base import Retriever

_factory: dict[str, Callable[[], Retriever]] = {}


def register(name: str, factory: Callable[[], Retriever]) -> None:
    if name in _factory:
        raise ValueError(f"retriever already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> Retriever:
    try:
        return _factory[name]()
    except KeyError as exc:
        raise KeyError(f"unknown retriever: {name!r}") from exc


get_retriever = get


def names() -> set[str]:
    return set(_factory.keys())


registry = type(
    "_RetrieverRegistryNS",
    (),
    {"get": staticmethod(get), "names": staticmethod(names), "register": staticmethod(register)},
)()


def _register_defaults() -> None:
    from cliver_playbook.app.rag.retrieval import bm25_only, pgvector_hybrid

    register("bm25-only", lambda: bm25_only.Bm25OnlyRetriever())
    register("pgvector-hybrid", lambda: pgvector_hybrid.PgvectorHybridRetriever())


_register_defaults()
