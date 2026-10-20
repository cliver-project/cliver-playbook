---
name: cliver-playbook-assemble-project
description: Assemble a new production-grade project from cliver-playbook. Use when starting a new app or service, when a project should reuse cliver-playbook, or when deciding which playbook capabilities to compose, configure, copy, or build from scratch.
license: Apache-2.0
compatibility: Requires git and network access, Python 3.12+ with uv, Node.js with pnpm, and Docker for the production gates.
---

# Assemble a project from cliver-playbook

cliver-playbook is a library of composable backend and frontend packages.
This skill takes an empty directory to a running, production-grade baseline:
the project composes the playbook infrastructure and owns only its domain.

The skill assumes no local cliver-playbook checkout. It fetches the release it
needs in step 0 and treats that clone as read-only reference material; the
published packages are the dependency. Paths beginning with `var/playbook/`
refer to that clone; `reference/` and `assets/` are relative to this skill
directory. Run the workflow from the new project's directory, not from inside a
playbook checkout.

The skill is published independently of package releases and always reflects
the latest guidance. A project pins its own playbook release tag (step 0);
this skill does not. Before relying on a documented name or signature, read the
matching package source in the `var/playbook` checkout; the seams are stable,
but fields and helpers can move between releases.

## Non-negotiables

- **Pin one release tag everywhere.** Backend pins use `==X.Y.Z`, frontend
  git refs use `#X.Y.Z`, and `project-manifest.yaml` records the same
  revision. Never depend on `main`, `HEAD`, or a branch.
- **One playbook version.** Every selected backend and frontend package uses
  the same tag.
- **Compose, then configure; copy, then vendor.** Vendor only when a required
  change cannot be expressed through an extension seam, and record why.
- **Never edit an installed package.** Infrastructure changes go back to the
  playbook (see step 7).
- **No secrets in the repository.** `.env` is gitignored; `.env.example`
  carries placeholders only. Never print a secret.
- **`app.include_router()` only.** `FastAPI.mount()` is forbidden (ADR-0017).
- **Model access goes through cliver-core.** If a capability is missing, add
  it to cliver-core; never call a model provider directly from project code.
- **The demo Items surface is a pattern, not a domain.** It may remain in a
  composed install; do not build the product on it.
- **English only** in code, comments, docs, and commits.

## Step 0 — Get the pinned playbook

The published packages are the dependency. The checkout is the reference and
the home of the assembly scripts.

```sh
PLAYBOOK_TAG=0.1.0          # the release this project pins
PLAYBOOK_REPO=https://github.com/cliver-project/cliver-playbook
mkdir -p var
git clone --depth 1 --branch "$PLAYBOOK_TAG" "$PLAYBOOK_REPO" var/playbook
```

The `0.1.0` literals throughout this skill's examples stand for the tag chosen
here; substitute the project's tag everywhere.

Add `/var/` to `.gitignore` if it is not already there. If `var/playbook`
already exists, confirm it is at the intended tag with
`git -C var/playbook describe --tags --exact-match`; do not assume it. If the
tag is missing, `git ls-remote --tags "$PLAYBOOK_REPO"` lists what exists;
pick the latest release, never a branch.

## Step 1 — Capture the brief and choose the smallest profile

Write one paragraph: who uses the product, the capabilities of the first
release, and what is explicitly out of scope. If the brief is missing, state
the assumptions and record them in `project-manifest.yaml`.

| Profile | Packages | Choose when |
|---|---|---|
| `minimal` | basic | Internal API or tool; no accounts |
| `web` | basic + user | People sign in; roles, permissions, admin |
| `rag` | basic + user + rag | A knowledge base with upload, search, chat |
| `mcp` | basic + user + rag + mcp | Agents call tools in addition to the web app |

Choose the smallest profile that covers the first release. Adding a package
later is a wiring change, not a rewrite; starting with `mcp` "for options"
adds surface that must then be tested and secured.

## Step 2 — Decide every capability: reuse, configure, create, or vendor

Read `reference/decision-guide.md` and produce a short table before writing
code. Every capability gets one disposition:

- **Reuse** — compose the package; no source change.
- **Configure** — set an existing Settings field, extension seam, or registry
  entry; no source change.
- **Create** — project domain code; the playbook has no opinion.
- **Vendor** — copy a package tree and own it. Requires a written reason no
  seam above can satisfy.

The default answers: infrastructure is reused, behavior is configured, domain
is created, and vendoring does not happen. Record the decisions in
`project-manifest.yaml` (`decisions:`), including why the profile was chosen
and every vendor entry.

## Step 3 — Plan and record the manifest

```sh
python3 var/playbook/scripts/assemble_project.py \
  --profile <profile> --mode <mode> --target . --dry-run
```

Create `project-manifest.yaml` from this template and edit it: real project
name, `playbook.revision` set to the tag from step 0, the selected backend and
frontend packages, `vendored: []` (or one entry per vendored package), and the
decision lines.

```yaml
project: example-app
playbook:
  source: https://github.com/cliver-project/cliver-playbook
  revision: "X.Y.Z"          # same tag as every dependency pin
mode: compose                # compose | vendor | generate
packages:
  backend:
    - cliver-playbook-app-basic
    - cliver-playbook-app-user
  frontend:
    - cliver-playbook-app-basic
    - cliver-playbook-app-user
vendored: []                 # required empty for mode: compose
decisions:
  - "Profile web: accounts and roles, no knowledge base or agent tools."
  - "Created the orders domain in a project migration chain; no playbook table altered."
```

The template also ships with this skill at
`assets/project-manifest.example.yaml` (relative to this file), and in the
playbook repository at
`skills/cliver-playbook-assemble-project/assets/`. Validate the manifest:

```sh
uv run --with pyyaml python \
  var/playbook/scripts/validate_project_manifest.py project-manifest.yaml
```

Do not continue while the validator reports errors.

## Step 4 — Scaffold and wire

Follow the reference that matches the work; do not improvise the seams.

- Backend: `reference/backend-composition.md` — dependencies, the Settings
  subclass, the app factory per profile, permissions, the project migration
  chain, the domain slice, and MCP tools.
- Frontend: `reference/frontend-composition.md` — git-tag install, pnpm
  overrides, shell files, routes/nav/i18n, Tailwind sources, and the dev
  proxy.
- Config and repository: copy `app.yaml`, `.env.example`, and
  `docker-compose.yml` from `var/playbook/`, change `app_name`, remove the
  sections for packages the project does not use, and keep every secret out.
  Add a project-owned `Makefile` and `.gitignore` (`var/`, `.env`,
  `node_modules/`, `dist/`, `__pycache__/`, `.venv/`).

The frontend shell is a copy of the matching playbook `dev/` shell: the `mcp`
shell is the full composition, and the smaller shells are the trimmed
versions. Copy the one for the chosen profile rather than hand-assembling a
shell from nothing.

## Step 5 — Build one real vertical slice

Before breadth, prove every seam with one domain capability end to end:
table + migration → permission code → service → API endpoint → frontend
page → route/nav → translation → tests. Keep the demo Items surface until
the slice works; it is harmless, and deleting it from a composed install is
not a supported seam.

Order matters: backend first, because the frontend follows the API contract;
tests with each layer, not at the end.

## Step 6 — Pass the production gates

Run every gate in `reference/quality-gates.md`. Report the command and its
actual result for each. A skipped or failing gate means the project is not
done; do not paper over it or declare success from inspection.

## Step 7 — Close the loop

When the project exposes a playbook gap, do not patch an installed package
and do not start an undocumented fork:

1. Reproduce against the pinned tag in the playbook repository.
2. Write the failing test first; implement in the owning package.
3. Run `make check` and `make verify-reference` in the playbook.
4. Update the package README or ADR when behavior or a decision changes
   (ADRs are append-only).
5. Release a new tag (`make release VERSION=X.Y.Z`) only with maintainer
   approval, then bump the project's pins.
6. If the gap is a missing gate or a repeated workaround, add it to
   `reference/quality-gates.md` or to the playbook's tests so the next
   project inherits the fix.

See `reference/upstream-loop.md`. A workaround that stays only in the project
has lowered the next project's starting quality.

## Definition of done

- [ ] Every dependency and git ref points at the same release tag.
- [ ] `project-manifest.yaml` validates; every vendor entry has a reason.
- [ ] `uv sync --frozen` and `pnpm install --frozen-lockfile` succeed with no
      workspace links.
- [ ] An empty database migrates through every chain, twice, in order.
- [ ] The app boots and `/api/v1/health` responds.
- [ ] Backend lint and tests pass; frontend typecheck, lint, and build pass.
- [ ] The first domain slice works through the UI and the API.
- [ ] The permission catalog includes the project codes; admin holds `*`.
- [ ] No `FastAPI.mount()`, no secrets, no client names, and no real
      deployment URLs in the repository.
- [ ] `var/`, `.env`, build output, and `node_modules/` are ignored;
      lockfiles are committed.
- [ ] Playbook feedback is recorded or upstreamed.

## Reference map

| File | Use |
|---|---|
| `reference/decision-guide.md` | Reuse / configure / create / vendor, with the exact seams |
| `reference/backend-composition.md` | Settings, app factory, permissions, migrations, domain, MCP tools |
| `reference/frontend-composition.md` | Install model, shell, routes, i18n, Tailwind, proxy |
| `reference/quality-gates.md` | The production checklist and its evidence |
| `reference/upstream-loop.md` | Improving the playbook after a project finds a gap |
