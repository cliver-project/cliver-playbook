"""Chunker registry: the public ``get_chunker`` + ``registry`` seam."""

from __future__ import annotations

from collections.abc import Callable

from .base import Chunker

_factory: dict[str, Callable[[], Chunker]] = {}


def register(name: str, factory: Callable[[], Chunker]) -> None:
    """Register a chunker factory under a name."""
    if name in _factory:
        raise ValueError(f"chunker already registered: {name!r}")
    _factory[name] = factory


def get(name: str) -> Chunker:
    """Resolve a registered chunker by name. Raises ``KeyError`` if unknown."""
    try:
        return _factory[name]()
    except KeyError as exc:
        raise KeyError(f"unknown chunker: {name!r}") from exc


# Alias the public API expects.
get_chunker = get


def names() -> set[str]:
    """Return the set of registered chunker names (for the UI dropdown)."""
    return set(_factory.keys())


# Backwards-compatible alias: callers (and tests) can use
# ``chunking.registry.get(name)`` as well as ``get_chunker(name)``.
# The class-instance form was tried first; an instance and a
# module-level namespace conflict on import, so the alias is the
# simpler shape.
registry = type(
    "_ChunkerRegistryNS",
    (),
    {"get": staticmethod(get), "names": staticmethod(names), "register": staticmethod(register)},
)()


# Eager registration at module import: importing the registry module
# pulls in every chunker so the names() set is complete after a
# single import. The chunker modules register themselves; this
# module's bottom triggers that import.
def _register_defaults() -> None:
    from . import code, docx, markdown, pdf, recursive

    register("recursive", lambda: recursive.RecursiveChunker())
    register("markdown", lambda: markdown.MarkdownChunker())
    register("code", lambda: code.CodeChunker())
    register("pdf", lambda: pdf.PdfChunker())
    register("docx", lambda: docx.DocxChunker())


_register_defaults()
