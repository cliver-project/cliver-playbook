"""Process-wide runtime state: settings binding and the database engine.

The design rules this module exists to enforce (ADR-0016):

- Importing a package has no side effects. Nothing here reads configuration
  files, creates an engine, or builds an app at import time.
- ``configure(settings)`` binds the process exactly once, from a package's
  ``create_app``. Afterwards every module-level ``settings`` proxy in the
  process (``LazySettings`` below) and every database accessor
  (``engine``/``session_factory``) answers from that single binding, so a
  composed application cannot end up with two settings worlds or two
  engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:  # the bound instance may be any package's Settings subclass
    from cliver_playbook.app.basic.settings import Settings


@dataclass
class _RuntimeState:
    """State created exactly once by ``configure`` (see module docstring)."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


_state: _RuntimeState | None = None


def configure(settings: Settings) -> Settings:
    """Bind the process settings instance and build the database engine.

    First call wins. Calling again with the SAME instance is a no-op — a
    package's ``create_app`` may delegate to another package's before adding
    its own routers. Calling again with a DIFFERENT instance raises: silently
    rebinding would leave earlier requests, engines and settings proxies
    pointing at two different worlds.

    Returns the bound instance for convenience.
    """
    global _state
    if _state is not None:
        if settings is not _state.settings:
            raise RuntimeError(
                "The runtime is already configured with a different Settings instance. "
                "Configure exactly once per process — typically by calling create_app()."
            )
        return _state.settings

    engine = create_async_engine(settings.db_url, future=True, pool_pre_ping=True)
    _state = _RuntimeState(
        settings=settings,
        engine=engine,
        # expire_on_commit=False keeps attributes readable on instances after
        # commit — the standard choice for request-scoped sessions handed out
        # by FastAPI dependencies.
        session_factory=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    return settings


def is_configured() -> bool:
    """True once ``configure`` has bound the process."""
    return _state is not None


def configured_settings() -> Settings | None:
    """The bound settings instance, or None before ``configure``."""
    return _state.settings if _state is not None else None


def engine() -> AsyncEngine:
    """The process-wide async engine (asyncpg over ``settings.db_url``)."""
    return _require_state().engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    """The process-wide async session factory bound to the runtime engine."""
    return _require_state().session_factory


async def dispose() -> None:
    """Dispose the engine's connection pool; a no-op before ``configure``.

    Call on application shutdown. Tests call it between cases: asyncpg
    connections are bound to the event loop that created them, and each test
    runs on a fresh one.
    """
    if _state is not None:
        await _state.engine.dispose()


def _require_state() -> _RuntimeState:
    if _state is None:
        raise RuntimeError(
            "The runtime is not configured: call create_app() (or configure(settings)) "
            "before using the database engine or session factory."
        )
    return _state


class LazySettings:
    """Deferred, process-aware settings accessor for one package's Settings class.

    Attribute access resolves to the process-bound instance when one exists,
    else to an instance of ``settings_cls`` built on first use and cached for
    the process. Construction is deferred so that importing a package's
    ``settings`` module reads no configuration files — the import-safety rule
    from ADR-0016.
    """

    def __init__(self, settings_cls: type) -> None:
        self._settings_cls = settings_cls
        self._fallback: Any = None

    def resolve(self) -> Any:
        """The effective settings instance (bound instance, else fallback)."""
        bound = configured_settings()
        if bound is not None:
            return bound
        if self._fallback is None:
            self._fallback = self._settings_cls()
        return self._fallback

    def __getattr__(self, name: str) -> Any:
        # Reached only for attributes missing on the proxy itself, so the
        # proxy's own internals never recurse through here.
        return getattr(self.resolve(), name)


def lazy_settings(settings_cls: type) -> LazySettings:
    """Create a ``LazySettings`` proxy bound to ``settings_cls``."""
    return LazySettings(settings_cls)
