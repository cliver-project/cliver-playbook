# Quality gates

A gate is passed only when its command ran in this session and produced the
expected result. "It should work", a code read, or a green run from before the
last change is not evidence. A skipped gate — including one skipped because
PostgreSQL is unavailable — is a failed gate.

Run the gates in order. When one fails, fix the cause and rerun it; do not
record a workaround as a pass. If the cause is a playbook defect, follow
`reference/upstream-loop.md` before continuing.

## Gate 0 — Repository hygiene

```sh
# The manifest must validate: same revision everywhere, known packages,
# mode/vendored consistency.
uv run --with pyyaml python \
  var/playbook/scripts/validate_project_manifest.py project-manifest.yaml
```

```sh
# Pins: one tag across all three surfaces.
grep -n 'cliver-playbook-app-.*==' pyproject.toml
grep -n 'cliver-playbook' package.json pnpm-workspace.yaml
grep -n '^  revision:' project-manifest.yaml
```

Expected: every backend pin is `==X.Y.Z`, every frontend URL and override is
`#X.Y.Z&path:...`, and the manifest says `revision: X.Y.Z`. Any `main`,
`HEAD`, branch name, or range is a failure.

```sh
# Secrets and local state are not tracked.
git check-ignore -q .env && echo ".env ignored"
git check-ignore -q var/ && echo "var/ ignored"
git check-ignore -q node_modules/ && echo "node_modules/ ignored"
git ls-files --error-unmatch .env >/dev/null 2>&1 && echo "FAIL: .env tracked"
git ls-files | grep -E '^(var/|node_modules/|dist/)' && echo "FAIL: local state tracked"
```

Also read `.env.example`: every value is a placeholder, every required key is
present, and no real hostname, client id, or credential appears anywhere in
the tracked tree. Never print a secret while checking; grep for key names, not
values.

## Gate 1 — Reproducible install

```sh
uv sync --frozen
pnpm install --frozen-lockfile
```

Expected: both succeed from the committed lockfiles, with no workspace link
to a local playbook checkout. Confirm the resolved versions:

```sh
uv pip list | grep cliver-playbook
pnpm list --depth 0 | grep cliver-playbook
```

Every installed playbook package reports the pinned version. If a package
resolves from a path outside the lockfile, stop: the project is not
reproducible.

## Gate 2 — Backend static checks

```sh
uv run ruff check
uv run ruff format --check
```

Expected: no findings. Do not add blanket per-file ignores to get green; fix
the code or narrow the rule with a written reason.

## Gate 3 — Backend tests

```sh
uv run pytest -q
```

Expected: zero failures, zero errors, and **zero skips** in the gate run. The
suite's `conftest.py` skips when PostgreSQL is unavailable; that is a local
convenience, not an acceptable CI result. Start the database first
(`make db-up`) and rerun.

Check that the run exercised real seams:

- The first project slice has an API test that asserts the permission denial
  (403/401), not only the happy path.
- The migration chain ran against the temp database; a test that patches the
  session layer is not a database test.
- Audit assertions read the row the request wrote, not a mock call.

## Gate 4 — Migrations from an empty database, twice

Use a scratch database. Never run this against a database with data.

```sh
# Point at an empty scratch database, then:
uv run python -m app.migrate
uv run python -m app.migrate
```

Expected: the first run applies `basic` → `user` → `rag` → project; the second
is a no-op. Neither run errors. Then inspect the version tables:

```sh
psql "$SYNC_DATABASE_URL" -c '\dt alembic_version*'
psql "$SYNC_DATABASE_URL" -c 'TABLE alembic_version_basic;'
psql "$SYNC_DATABASE_URL" -c 'TABLE alembic_version_user;'
psql "$SYNC_DATABASE_URL" -c 'TABLE alembic_version_rag;'
psql "$SYNC_DATABASE_URL" -c 'TABLE alembic_version_app;'
```

Expected: one version table per selected chain, each at its head; the project
table exists and points at the project's latest revision. The `rag` table is
absent for profiles `minimal` and `web`; `mcp` owns no chain.

Also verify that `alembic upgrade head` (the project chain alone) still works
after the packages are applied:

```sh
uv run alembic upgrade head
```

An empty database migrated only by the project chain is expected to fail if
the project references package tables; the aggregate runner is the supported
path.

## Gate 5 — Boot and health

```sh
uv run uvicorn --factory app.app:create_app --host 127.0.0.1 --port 8000
```

In another shell:

```sh
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/api/v1/version
```

Expected: `{"status":"ok"}` and the project's `app_name`. A health failure
means the process is up but the database is not reachable; do not treat `/`
returning HTML as a health check.

Read the startup log: no traceback, no warning about an unregistered settings
section, no "permission code not registered" error. Shut the server down
cleanly; a lifespan that hangs on shutdown is a finding.

For the `mcp` profile, the endpoint must answer (401 is acceptable when auth
is required; 500 is not):

```sh
curl -sS -o /tmp/mcp.out -w '%{http_code}\n' -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"gate","version":"0.0.0"}}}'
```

A body containing `RuntimeError: Task group is not initialized` means the MCP
session manager is not running: the lifespan is missing or `create_app` was
bypassed. Authenticate as an admin and repeat to see the tool list; then check
that a project tool is present and a permission-gated tool returns a
structured denial for a caller without the code.

## Gate 6 — Frontend checks and build

```sh
pnpm typecheck
pnpm lint
pnpm build
```

Expected: all three pass. Then verify Tailwind scanned every package. Each
package has a utility used only in its own pages:

```sh
grep -q 'break-all' dist/assets/*.css    # user
grep -q 'max-h-80'  dist/assets/*.css    # rag
grep -q 'max-w-48'  dist/assets/*.css    # mcp
```

A missing sentinel means the package's `@source` path is wrong or resolves
through a symlink; the build still succeeds and the page is silently
unstyled. Fix the path (`node-linker=hoisted`, real directory) and rebuild.
Re-pick the sentinel when a release changes the utility, never delete the
gate.

## Gate 7 — Security and authorization

- **No `FastAPI.mount()`:**

  ```sh
  grep -rn "\.mount(" app/ || echo "no mount calls"
  ```

  Any hit is a failure. All routers are included with `include_router()`.

- **No secrets in the tree:** rerun the Gate 0 greps, including generated
  files and the README. `.env` exists locally, is ignored, and was never
  committed.

- **Permission catalog:** `require_perm` validates at import, so a successful
  boot already proves every project code is registered before its router
  imported. Confirm the catalog and the admin wildcard:

  ```sh
  curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" \
    http://127.0.0.1:8000/api/v1/admin/permissions | grep -o 'orders:[a-z]*'
  curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" \
    http://127.0.0.1:8000/api/v1/auth/me | grep -o '"permissions":\[[^]]*\]'
  ```

  Expected: the project codes appear once each and the admin's permissions
  include `*`. A duplicate or conflicting registration raises at import, so a
  silent catalog miss is not possible — but a code that exists while no role
  holds it is: assign it to the intended role and test that role.

- **Unauthenticated denial:** for profiles with identity, a project endpoint
  without a token returns 401 (not 200, not 500). With a token lacking the
  code, it returns 403. Test both; the server is the enforcement point, and
  `RequirePerm` only hides UI.

- **Audit:** perform one project mutation and one MCP tool call (mcp profile),
  then read the audit endpoint as an admin:

  ```sh
  curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" \
    'http://127.0.0.1:8000/api/v1/admin/audit?limit=20'
  ```

  Expected: one row per action with the actor, action, target, IP/user agent
  (`RequestMetaMiddleware`), and a sanitized payload. A missing row means the
  write path bypassed `write_audit`.

- **OAuth 2.1 (if enabled):** `/.well-known/oauth-protected-resource` and the
  authorization-server metadata resolve, and the configured public base URL
  matches the URL agents will use. A mismatch here surfaces only at an
  external agent's connect time.

- **Secrets at rest:** runtime-settings secret fields are write-only and are
  masked on read; an environment-managed secret is read-only in the UI. Never
  store a bootstrap credential in a runtime settings section.

## Gate 8 — The first vertical slice, end to end

One capability, all layers:

- [ ] A row can be created through the UI, appears in the list after refresh,
      and can be edited and deleted.
- [ ] The same operations fail with a clear message for a user without the
      write permission.
- [ ] The list endpoint enforces pagination/limits in the service, not only in
      the client.
- [ ] The migration that created the table is in the project chain and has
      been applied from empty at least once (Gate 4 covers this).
- [ ] An audit row exists for each mutation.
- [ ] The page is reachable from the header and its nav entry is filtered for
      a viewer without the read permission.

Record the HTTP status codes observed, not just "works".

## Gate 9 — Configuration behavior

- **Environment-only boot:** with no `app.yaml` and no `.env`, the app starts
  from code defaults, or fails with a named required setting. It must not
  crash on a missing optional file.
- **Precedence:** setting a field in `app.yaml`, then overriding it with
  `CLIVER_<FIELD>`, changes the effective value. Runtime overrides applied
  through the admin settings page survive a restart and outrank `app.yaml`.
- **Feature switches:** every optional package block that is disabled
  (`oauth21_enabled: false`, OIDC with no providers) leaves the app bootable
  and its routes absent, not half-mounted.
- **Admin settings page:** the project's section renders, validates, and
  persists; a rejected value leaves the previous state unchanged (validation
  completes before mutation).
- **Startup settings validation:** an invalid value in `app.yaml` fails the
  boot with a clear message. A boot that ignores the bad value is a finding.

## Gate 10 — Operability

- [ ] `docker compose up -d db` (or the project's documented equivalent)
      brings up PostgreSQL; `make db-init` applies every chain with no manual
      step.
- [ ] The README has: prerequisites, environment variables with placeholders,
      install, migrate, run, test, and the deployment shape.
- [ ] A fresh clone following only the README reaches a running app.
- [ ] Backups and restore are documented for the database, and the migration
      step is part of the deploy procedure.
- [ ] Logs go to stdout; no secret appears in a log line.
- [ ] The production process does not run with `--reload`, does not serve the
      dev server, and binds through the documented proxy/origin.
- [ ] `.gitignore` excludes `var/`, `.env`, `node_modules/`, `dist/`,
      `__pycache__/`, `.venv/`; lockfiles are committed.

## Evidence record

Report one line per gate in the handoff:

```text
Gate 0 hygiene     PASS  manifest valid; pins 0.1.0 everywhere
Gate 1 install     PASS  uv sync --frozen; pnpm --frozen-lockfile
Gate 2 lint        PASS  ruff check; ruff format --check
Gate 3 tests       PASS  pytest -q: 42 passed, 0 skipped
Gate 4 migrations  PASS  empty DB: basic→user→rag→app; second run no-op
Gate 5 boot        PASS  /api/v1/health 200; /mcp initialize 200
Gate 6 frontend    PASS  typecheck/lint/build; 3 CSS sentinels found
Gate 7 security    PASS  no mount(); 401/403 verified; audit row present
Gate 8 slice       PASS  create/list/edit/delete through UI and API
Gate 9 config      PASS  env > app.yaml; invalid value fails boot
Gate 10 operability PASS README reaches a running app on a fresh clone
```

If a gate did not run, write `NOT RUN` and the reason. Do not write `PASS`
from the diff, from a previous run, or from a smoke test that only checked
the process was listening.

## When a gate fails

1. Reproduce it deterministically.
2. Find the root cause; do not patch the assertion, add a skip, or loosen a
   checker.
3. If the cause is in project code, fix it and rerun the gate plus its
   neighbors.
4. If the cause is in the playbook — a missing seam, a wrong default, a
   missing test helper, an undocumented constraint — follow
   `reference/upstream-loop.md`. Fix it in the pinned checkout, prove it with a
   test, and only then decide whether to vendor (rare) or wait for a release.
5. If the cause is environmental, document the prerequisite in the README and
   in the gate itself so the next project does not rediscover it.
