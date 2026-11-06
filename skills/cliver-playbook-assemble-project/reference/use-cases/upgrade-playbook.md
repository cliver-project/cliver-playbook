# Upgrade the pinned playbook release

## Use when

A project should move from its current playbook tag to a newer release. An
upgrade is one tag across every backend and frontend package, plus migrations
and the production gates; it is not a partial bump.

Profile: any.

## Do

### 1. Choose the target and refresh the checkout

```sh
OLD_TAG=$(git -C var/playbook describe --tags --exact-match)
NEW_TAG=X.Y.Z
PLAYBOOK_REPO=https://github.com/cliver-project/cliver-playbook

git -C var/playbook fetch --depth 1 origin tag "$NEW_TAG"
git -C var/playbook checkout "$NEW_TAG"
git -C var/playbook describe --tags --exact-match   # must print NEW_TAG
```

Review what changed:

```sh
git -C var/playbook log --oneline "$OLD_TAG".."$NEW_TAG"
```

Read the changed package READMEs or release notes for renamed settings and new
seams; do not read the whole diff.

### 2. Update every pin together

- Backend `pyproject.toml`: every `cliver-playbook-app-*==X.Y.Z`.
- Frontend `package.json`: every git URL `#X.Y.Z&path:/packages/frontend/...`.
- `pnpm-workspace.yaml`: every `overrides` entry (all four packages, even the
  ones the project does not import directly).
- `project-manifest.yaml`: `playbook.revision: "X.Y.Z"`.

```sh
rg -n 'cliver-playbook-app|playbook.revision|#X\.Y\.Z' \
  pyproject.toml package.json pnpm-workspace.yaml project-manifest.yaml
```

The old tag must not remain anywhere.

### 3. Refresh both lockfiles

```sh
uv lock
pnpm install
```

Run the frozen installs CI will use:

```sh
uv sync --frozen
pnpm install --frozen-lockfile
```

Commit `uv.lock` and `pnpm-lock.yaml` with the pin changes.

### 4. Apply the migrations

```sh
uv run python -m app.migrate       # basic -> user -> rag -> project
```

Read every new revision the packages added before applying it to production.
The project's chain still runs last. Confirm `upgrade head` is idempotent by
running it twice against a scratch database.

### 5. Run the production gates

```sh
uv run ruff check
uv run pytest
pnpm typecheck
pnpm lint
pnpm build
```

Then boot the app, check `/api/v1/health`, exercise the first vertical slice,
and run the CSS sentinel greps from `reference/quality-gates.md`. A dependency
bump can pass unit tests and still drop package styles.

### 6. Re-check the seams the project touched

Search the project for imports of symbols that moved or changed:

```sh
rg -n 'from cliver_playbook|from "cliver-playbook' app src
```

If a use-case page is stale, update it in the same playbook release (step 7 in
`SKILL.md`). If the project carried a workaround for a gap the new release
fixes, remove the workaround and record why.

## Verify

- One tag everywhere (`rg` finds no old tag).
- Frozen installs succeed from a clean checkout.
- Every migration chain applies to an empty database, in order.
- Health, tests, typecheck, lint, and build pass.
- The first vertical slice works through the UI and API.
- No vendored copy shadows an upgraded installed package.

## Pitfalls

- **Never mix tags.** A backend at `0.2.0` and a frontend at `0.1.0` is an
  unsupported combination even when both install.
- **Do not skip the migration step.** A new package feature may assume a table
  or column that only its chain creates.
- **Do not edit the `var/playbook` checkout to make the project compile.** It
  is a tag reference; a needed change goes upstream.
- **Removing or renaming a provider/capability is usually configuration, not a
  reason to vendor.** Check the decision guide before copying.
- **The frontend lockfile must be refreshed after every git-ref change.**
  `pnpm install --frozen-lockfile` fails rather than silently resolving.
- **Do not bump the backend without the frontend, or vice versa.**

## Source of truth

- `var/playbook/skills/cliver-playbook-assemble-project/reference/quality-gates.md`
  — the gates and the evidence record.
- `var/playbook/skills/cliver-playbook-assemble-project/reference/upstream-loop.md`
  — when the upgrade exposes a gap.
- `project-manifest.yaml` — the recorded revision and decisions.
- Deep dive: `reference/quality-gates.md`.
