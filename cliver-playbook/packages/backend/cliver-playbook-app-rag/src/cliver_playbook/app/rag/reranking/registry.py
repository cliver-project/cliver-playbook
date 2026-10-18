"""Reranker registry."""

from __future__ import annotations

from collections.abc import Callable

from cliver_playbook.app.rag.reranking.base import Reranker

_factory: dict[str, Callable[[], Reranker]] = {}
# One shared instance per name (see the embedder registry): a model-backed
# reranker's lazy-load lock and loaded weights live on the instance, so
# constructing one per call would reload the model every time.
_instances: dict[str, Reranker] = {}


def register(name: str, factory: Callable[[], Reranker]) -> None:
    if name in _factory:
        raise ValueError(f"reranker already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> Reranker:
    """Return the shared instance registered under ``name``."""
    instance = _instances.get(name)
    if instance is not None:
        return instance
    try:
        factory = _factory[name]
    except KeyError as exc:
        raise KeyError(f"unknown reranker: {name!r}") from exc
    instance = factory()
    _instances[name] = instance
    return instance


get_reranker = get


def names() -> set[str]:
    return set(_factory.keys())


registry = type(
    "_RerankerRegistryNS",
    (),
    {"get": staticmethod(get), "names": staticmethod(names), "register": staticmethod(register)},
)()


def _register_defaults() -> None:
    from cliver_playbook.app.rag.reranking import bge, noop

    register("bge-reranker-v2-m3", lambda: bge.BgeRerankerV2M3())
    register("noop", lambda: noop.NoopReranker())


_register_defaults()
