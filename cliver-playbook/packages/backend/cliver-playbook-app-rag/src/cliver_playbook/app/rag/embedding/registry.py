"""Embedder registry."""

from __future__ import annotations

from collections.abc import Callable

from cliver_playbook.app.rag.embedding.base import Embedder

_factory: dict[str, Callable[[], Embedder]] = {}


def register(name: str, factory: Callable[[], Embedder]) -> None:
    if name in _factory:
        raise ValueError(f"embedder already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> Embedder:
    try:
        return _factory[name]()
    except KeyError as exc:
        raise KeyError(f"unknown embedder: {name!r}") from exc


get_embedder = get


def names() -> set[str]:
    return set(_factory.keys())


registry = type(
    "_EmbedderRegistryNS",
    (),
    {"get": staticmethod(get), "names": staticmethod(names), "register": staticmethod(register)},
)()


def _register_defaults() -> None:
    from cliver_playbook.app.rag.embedding import bge_m3, stub

    register("stub", lambda: stub.StubEmbedder())
    register("bge-m3", lambda: bge_m3.BgeM3Embedder())


_register_defaults()
