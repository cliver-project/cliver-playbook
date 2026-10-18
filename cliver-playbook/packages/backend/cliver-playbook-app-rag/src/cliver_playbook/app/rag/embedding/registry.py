"""Embedder registry."""

from __future__ import annotations

from collections.abc import Callable

from cliver_playbook.app.rag.embedding.base import Embedder

_factory: dict[str, Callable[[], Embedder]] = {}
# One shared instance per name. A fresh wrapper per call would throw away
# the implementation's lazy-load cache and its load lock, so a model-backed
# embedder would reload its weights on every request.
_instances: dict[str, Embedder] = {}


def register(name: str, factory: Callable[[], Embedder]) -> None:
    if name in _factory:
        raise ValueError(f"embedder already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> Embedder:
    """Return the shared instance registered under ``name``.

    Construction is deferred to the first lookup and memoized. Callers
    must not mutate the returned object; the shipped implementations keep
    their only mutable state behind an internal lock.
    """
    instance = _instances.get(name)
    if instance is not None:
        return instance
    try:
        factory = _factory[name]
    except KeyError as exc:
        raise KeyError(f"unknown embedder: {name!r}") from exc
    instance = factory()
    _instances[name] = instance
    return instance


get_embedder = get


def names() -> set[str]:
    return set(_factory.keys())


registry = type(
    "_EmbedderRegistryNS",
    (),
    {"get": staticmethod(get), "names": staticmethod(names), "register": staticmethod(register)},
)()


def _register_defaults() -> None:
    from cliver_playbook.app.rag.embedding import bge_base_zh, bge_m3, stub

    register("stub", lambda: stub.StubEmbedder())
    register("bge-m3", lambda: bge_m3.BgeM3Embedder())
    register("bge-base-zh-v1.5", lambda: bge_base_zh.BgeBaseZhEmbedder())


_register_defaults()
