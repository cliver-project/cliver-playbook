"""A name-keyed registry for one stage family.

Registration takes a factory rather than an instance, matching the rag
package's registries. A duplicate name is a programming error (two
implementations claiming the same config value), so it raises at import
time instead of depending on import order.

``get`` returns a fresh instance. Stage objects are stateless in v1, so
this is cheap and keeps one configured source from leaking into another.
"""

from __future__ import annotations

from collections.abc import Callable


class Registry[T]:
    """A registry of stage factories, keyed by their public name."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._factories: dict[str, Callable[[], T]] = {}

    @property
    def kind(self) -> str:
        return self._kind

    def register(self, name: str, factory: Callable[[], T]) -> None:
        if name in self._factories:
            raise ValueError(f"duplicate {self._kind} registration: {name!r}")
        self._factories[name] = factory

    def get(self, name: str) -> T:
        try:
            factory = self._factories[name]
        except KeyError:
            known = ", ".join(sorted(self._factories)) or "(none)"
            raise KeyError(f"unknown {self._kind}: {name!r}; known: {known}") from None
        return factory()

    def names(self) -> list[str]:
        return sorted(self._factories)
