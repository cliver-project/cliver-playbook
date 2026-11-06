# Adopt cliver-playbook in an existing project

## Use when

- A project already has its own FastAPI and/or React code and should start
  using cliver-playbook.
- A project already composes some packages and needs another one (for example
  basic-only → web, or web → rag/mcp).
- You are **not** creating a project from an empty directory. For that, follow
  the workflow in `SKILL.md`.

## Do

### 1. Pin exactly one release

```sh
PLAYBOOK_TAG=X.Y.Z
PLAYBOOK_REPO=https://github.com/cliver-project/cliver-playbook

# A checkout is the read-only source reference, not the dependency.
test -d var/playbook || git clone --depth 1 --branch "$PLAYBOOK_TAG" "$PLAYBOOK_REPO" var/playbook
git -C var/playbook describe --tags --exact-match   # must print the tag
```

Add `var/` and `.env` to `.gitignore`. If the project has a
`project-manifest.yaml`, set `playbook.revision` to the same tag; if it does
not, create one from `assets/project-manifest.example.yaml` and validate it
with `var/playbook/scripts/validate_project_manifest.py`.

### 2. Select the smallest package set

| Need | Backend packages | Frontend packages |
|---|---|---|
| API only | `basic` | `basic` |
| Accounts, roles, admin | `basic`, `user` | `basic`, `user` |
| Knowledge base | `basic`, `user`, `rag` | `basic`, `user`, `rag` |
| Agent tools | `basic`, `user`, `rag`, `mcp` | `basic`, `user`, `rag`, `mcp` |

Backend: pin every package to `==X.Y.Z`. Frontend: use the git URL
`github:cliver-project/cliver-playbook#X.Y.Z&path:/packages/frontend/<name>`
for every selected package, and list **all four** frontend packages in the
pnpm `overrides` so a sibling's version pin never reaches a registry.

### 3. Wire the backend

- **Settings**: subclass the most-derived selected package; do not define a
  parallel `Settings`.
- **App factory**: call `runtime.configure()` once, include package `ROUTERS`
  before project routers, and wrap the lifespan with `settings_lifespan`.
- **User profiles**: add `RequestMetaMiddleware` and, when `oauth21_enabled`,
  `mount_oauth_routes(app)`.
- **MCP profile**: additionally import `app.tools` and enter
  `install_streamable_app()` inside the lifespan.
- **Migrations**: run every chain in dependency order (`basic` → `user` →
  `rag`) and then the project chain; `mcp` owns no chain.
- **Permissions**: import `app.permissions` before any router or tool module
  imports, and before the identity chain seeds roles.

Use the per-profile tables in `reference/backend-composition.md`; do not
reconstruct them from memory.

### 4. Wire the frontend

- Call `installAuthClient()` once, before the first request, for every profile
  that includes `user`.
- Pass every selected package's translation bundle to `createI18n()`, with the
  project bundle last.
- Keep the provider order: query client → theme → router → auth.
- Add the package route arrays and nav items to the app's route table; never
  edit a package to accept them.
- Add one Tailwind `@source` per package, pointing at the **real** directory
  (the scanner ignores symlinks); keep `node-linker=hoisted`.

### 5. Verify the adoption

```sh
uv sync --frozen
uv run python -m app.migrate          # or the project's runner
uv run uvicorn --factory app.app:create_app --port 8000
curl -fsS http://127.0.0.1:8000/api/v1/health

uv run pytest
pnpm install --frozen-lockfile
pnpm typecheck && pnpm lint && pnpm build
```

Then open the UI and exercise one existing package surface (sign in, admin
page, RAG page, or the MCP playground). A clean install is not proof that the
new package is composed.

## Verify

- The pinned checkout prints the intended tag.
- Every dependency, frontend git ref, pnpm override, and manifest revision
  carries the same `X.Y.Z`.
- An empty database migrates through every selected chain in order.
- The app boots and `/api/v1/health` responds.
- The selected package's UI or endpoint works end to end.

## Pitfalls

- Adding `user` without `RequestMetaMiddleware` leaves audit rows without
  caller metadata.
- Importing a project router before `app.permissions` raises at import time.
- Adding a frontend package without its `@source` silently omits its styles.
- Two React instances, two query clients, or two i18next instances break the
  composed app; the app owns exactly one of each.
- Do not re-scaffold the project or overwrite its existing shell when adding a
  package. Change only the package-specific wiring.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/runtime.py`
  — `configure`, `LazySettings`.
- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/app.py`
  — the reference composed factory.
- `var/playbook/packages/frontend/cliver-playbook-app-mcp/dev/` — the full
  frontend composition.
- Deep dives: `reference/backend-composition.md`,
  `reference/frontend-composition.md`, `reference/decision-guide.md`.
