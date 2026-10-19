# ADR-0016: Extensible settings and the process runtime

**Status:** Accepted (2026-10-16)
**Context:** Each template had its own `config.py` with a module-level
`settings = get_settings()` and a module-level engine: importing any module
read configuration files and bound a DSN, and two templates could not coexist
in one process because each defined its own Settings class. Packaging the code
also made the old `__file__`-anchored config paths actively wrong — they point
into site-packages once installed.

## Decision

1. **One Settings inheritance chain mirrors the dependency chain**:
   `basic.settings.Settings` holds the common fields (database_url, app_name,
   log_level) plus the layering machinery and URL derivation;
   `user.settings.Settings` subclasses it to add identity/OIDC fields, and
   `mcp.settings.Settings` extends user. No package redefines inherited fields,
   and the layering precedence (env > .env > app.yaml > field defaults) is
   implemented exactly once.
2. **The module-level `settings` is a lazy proxy.** `LazySettings.resolve()`
   returns the process-bound instance, or — when the process was never
   configured — lazily builds that package's own `Settings()` on first
   attribute access. Importing a settings module therefore reads no config.
   `get_settings()` is kept as a delegating accessor for existing call sites.
3. **`basic.runtime` owns process state.** `configure(settings)` — first call
   wins; the same instance again is a no-op; a different instance raises —
   creates the async engine and session factory. `engine()` and
   `session_factory()` raise before configuration, and `dispose()` closes the
   pool. Every package's `create_app()` calls `configure` before anything
   touches the database.
4. **Configuration discovery is CWD-relative**, not `__file__`-relative: the
   application root is the nearest ancestor of the current working directory
   containing `app.yaml` or `.env`. `$CLIVER_CONFIG_FILE` remains a hard
   override, and `Settings.__init__` injects the resolved `.env` unless the
   caller passed `_env_file` explicitly — tests keep exact control over the
   dotenv layer.
5. **No settings-driven API prefix.** Routers carry static prefixes
   (ADR-0015): an `APIRouter` prefix is fixed at import time, so a configured
   prefix would freeze whichever Settings instance happened to load first while
   hiding the URL surface from the route table.

## Why

- Import purity is what makes composition safe: importing two packages (or
  running pytest collection, alembic autogenerate, a `python -c "import ..."`
  probe) can never bind a database or fail on a missing config file.
- One binding per process means one settings world and one engine for a
  composed application, regardless of which package's entry point runs first.
- Restoring an `@lru_cache`-style global would silently reintroduce the
  import-time instantiation this decision removes.

## Non-goals

- Per-request or per-module dependency injection of settings — the process
  binding is deliberately global. Tests that need isolated settings construct
  `Settings(**overrides)` directly, as the config tests do.
- Per-package `.env`/app.yaml files: configuration belongs to the application,
  not to the libraries it composes.

## Amendments

- **2026-10-19 — runtime settings layer (ADR-0021).** A persisted,
  module-owned layer now sits between `.env` and `app.yaml`: effective
  precedence is env > `.env` > runtime overrides > `app.yaml` > defaults.
  `configure()` also stores a deep baseline copy for reset. This refines
  decision 1's precedence list and the runtime's responsibilities; the
  process-binding rule and the layering machinery are unchanged.
