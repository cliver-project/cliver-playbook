"""LLM registry."""

from __future__ import annotations

from collections.abc import Callable

from cliver_playbook.app.rag.llm.base import LLM

_factory: dict[str, Callable[[], LLM]] = {}


def register(name: str, factory: Callable[[], LLM]) -> None:
    if name in _factory:
        raise ValueError(f"llm already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> LLM:
    try:
        return _factory[name]()
    except KeyError as exc:
        raise KeyError(f"unknown llm: {name!r}") from exc


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
