"""LLM registry."""

from __future__ import annotations

from collections.abc import Callable

from cliver_playbook.app.rag.llm.base import LLM

_factory: dict[str, Callable[[], LLM]] = {}
# One shared instance per name, uniform with the other stage registries.
_instances: dict[str, LLM] = {}


def register(name: str, factory: Callable[[], LLM]) -> None:
    if name in _factory:
        raise ValueError(f"llm already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> LLM:
    """Return the shared instance registered under ``name``."""
    instance = _instances.get(name)
    if instance is not None:
        return instance
    try:
        factory = _factory[name]
    except KeyError as exc:
        raise KeyError(f"unknown llm: {name!r}") from exc
    instance = factory()
    _instances[name] = instance
    return instance


get_llm = get


def names() -> set[str]:
    return set(_factory.keys())


registry = type(
    "_LlmRegistryNS",
    (),
    {"get": staticmethod(get), "names": staticmethod(names), "register": staticmethod(register)},
)()


def _register_defaults() -> None:
    from cliver_playbook.app.rag.llm import stub

    register("stub", lambda: stub.StubLLM())


_register_defaults()
