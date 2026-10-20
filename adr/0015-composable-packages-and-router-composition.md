# ADR-0015: Composable packages and router composition

**Status:** Accepted (2026-10-16). Supersedes ADR-0002.
**Context:** The library was three whole-tree template copies (service scaffold,
user management, MCP server), each carrying every other's files. Reuse meant
copy-merge with REPLACE/EDIT manifests and a drift checker; every shared fix had
to be replayed three times, and the fixed `app` package name plus the three-token
rename surface existed only to make copy-merge deterministic.

## Decision

1. **The library ships as independent, publishable Python distributions**:
   `cliver-playbook-app-basic`, `cliver-playbook-app-user` and
   `cliver-playbook-app-mcp`, importing as `cliver_playbook.app.<name>`.
   `cliver_playbook/` and `cliver_playbook/app/` are PEP 420 namespace
   directories — deliberately without `__init__.py` — so several
   distributions' portions merge in one environment.
2. **Packages are editable-installable and mutually importable.** Each uses a
   src-layout with hatchling `dev-mode-dirs = ["src"]`, so an editable install
   is a plain path entry pointing at `src/`. `dev-mode-exact` is forbidden: it
   requires `__init__.py` files and its import finder would shadow sibling
   packages' namespace portions. Monorepo development resolves members through
   the root uv workspace; a consuming project installs a package with
   `python -m pip install -e ../cliver-playbook-app-<name>` into its venv.
3. **Cross-package dependencies are real dependencies**, declared in
   `[project.dependencies]` (user depends on basic, mcp on user) — never
   copied code, so a fix lands once and every consumer upgrades into it.
4. **Router composition goes through `include_router`.** Each package exposes
   `api/routes.py` with `ROUTERS: list[APIRouter]`, every router carrying a
   unique path prefix. A composed application is exactly:

   ```python
   for router in [*basic.ROUTERS, *user.ROUTERS, *mcp.ROUTERS]:
       app.include_router(router)
   ```

   Mounting sub-applications is not used for cross-package composition: a
   mounted sub-app hides its routes from the parent's route table, and
   assembling an app inside a package would break import purity (rule 6).
5. **Every package owns its settings subclass, its Alembic chain and its
   self-application.** Chains live inside their package and are tracked in
   per-package version tables (`alembic_version_<name>`), applied by calling
   each package's `run_migrations_online()` in dependency order; packages never
   edit each other's migration history. Each package also ships `create_app()`
   and `python -m cliver_playbook.app.<name>` so it can run alone.
6. **Importing a package has no side effects**: no app assembled, no config
   file read, no engine created at import time (ADR-0016 carries the
   mechanism).

## Why

- One library instead of three drifting copies: shared behaviour changes once.
- The copy manifests, REPLACE/EDIT discipline and drift checker are retired
  along with the physical copies they policed.
- A new project still starts fast: the skill copies the source of the chosen
  packages into the project and wires the router list. The repository remains
  the single place the code evolves.

## Non-goals

- Publishing to a package index. Packages are consumed from this repository
  (workspace or path installs); nothing here prepares for PyPI.
- Keeping the fixed `app` package name or the `cliver_app` rename token — with
  composition there is nothing to copy-merge or rename. The display-name and
  `CLIVER_` env-prefix conventions are retained.
