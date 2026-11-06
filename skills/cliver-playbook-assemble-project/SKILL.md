---
name: cliver-playbook-assemble-project
description: Assemble or extend a production-grade project on cliver-playbook. Use when starting a new app or service, when an existing project should adopt a playbook package or capability, when adding a backend or frontend feature (settings, permissions, OIDC, pagination, RAG, MCP, pages), or when deciding what to compose, configure, copy, or build.
license: Apache-2.0
compatibility: Requires git and network access, Python 3.12+ with uv, Node.js with pnpm, and Docker for the production gates.
---

# Assemble a project from cliver-playbook

cliver-playbook is a library of composable backend and frontend packages.
This skill takes an empty directory to a running, production-grade baseline,
and it extends a project that already composes the playbook. The project
composes the playbook infrastructure and owns only its domain.

## Reading protocol (do this first)

This skill is a router, not a book. The large reference files are deep dives,
not required reading. Stop at the first answer:

1. **Read this file only.** Do not open `reference/` in bulk.
2. **Choose one row** from the use-case catalog below. Read that one file.
   Do not read neighboring recipes "for context".
3. **Use the recipe's exact imports.** Its "Source of truth" list names the
   module and symbol. If a signature is unclear, search the pinned checkout
   (`rg -n "Symbol" var/playbook/packages/...`) and read only the matched
   lines, not the whole package.
4. **Open a deep dive only when the recipe links to a section you need.**
   Read that section, not the whole file.
5. **Stop when the recipe's verification passes.** If no recipe fits, use the
   decision rules below and record the gap for step 7. Do not improvise by
   reading implementation.

The goal is to read one task page and the symbols it names, not the playbook
source tree. A recipe that is insufficient is a skill bug: fix the recipe.

## Choose the entry point

- **New project, or first playbook adoption:** follow steps 0–7. Use the full
  composition references once for the initial shell, then one use-case page per
  capability.
- **Existing project already on the playbook:** skip to the use-case catalog.
  Do not re-scaffold or re-read the assembly steps.
- **Existing project not yet on the playbook:** read
  `reference/use-cases/adopt-playbook.md` first, then the capability recipe.
- **Upgrading the pinned release:** read
  `reference/use-cases/upgrade-playbook.md` only.

If `var/playbook` is absent, create it at the project's pinned tag (step 0)
before opening any recipe's "Source of truth" path. Do not read from a random
newer checkout.

The skill assumes no local cliver-playbook checkout. It fetches the release it
needs in step 0 and treats that clone as read-only reference material; the
published packages are the dependency. Paths beginning with `var/playbook/`
refer to that clone; `reference/` and `assets/` are relative to this skill
directory. Run the workflow from the new project's directory, not from inside a
playbook checkout.

The skill is published independently of package releases and always reflects
the latest guidance. A project pins its own playbook release tag (step 0);
this skill does not. The seams are stable, but fields and helpers can move
between releases; the recipe's exact source path is the lookup, not a license
to read the package.

## Use-case catalog

Find the row that matches the task. Read that one file. The profile column
names the smallest composition where the recipe applies (`minimal` = basic,
`web` = basic + user, `rag` = + rag, `mcp` = + mcp).

| Task | Read this one file | Profile |
|---|---|---|
| Adopt the playbook in an existing project, or add a package | `reference/use-cases/adopt-playbook.md` | any |
| Add a domain table, migration, service, and API | `reference/use-cases/add-backend-domain-slice.md` | any |
| Add or change permission codes | `reference/use-cases/add-backend-permission-codes.md` | web, rag, mcp |
| Add a project backend setting | `reference/use-cases/configure-backend-settings.md` | any |
| Add an admin-editable settings section | `reference/use-cases/add-runtime-settings-section.md` | web, rag, mcp |
| Configure SSO / OIDC / WeChat / Alipay login | `reference/use-cases/configure-oidc-login.md` | web, rag, mcp |
| Paginate a backend endpoint | `reference/use-cases/paginate-backend-endpoint.md` | any |
| Add an MCP tool | `reference/use-cases/add-mcp-tool.md` | mcp |
| Add a RAG stage | `reference/use-cases/add-rag-stage.md` | rag, mcp |
| Add a frontend page, route, and nav entry | `reference/use-cases/add-frontend-page.md` | any |
| Add an entity CRUD page | `reference/use-cases/add-frontend-crud-page.md` | any |
| Add a paged list page | `reference/use-cases/add-frontend-paged-list.md` | any |
| Brand the shell (colors, title, copy) | `reference/use-cases/theme-and-branding.md` | any |
| Upgrade the pinned playbook release | `reference/use-cases/upgrade-playbook.md` | any |

Each recipe follows the same shape: **Use when**, **Do**, **Verify**,
**Pitfalls**, **Source of truth**. The last section is the only place to open
source; it names the module and symbol, not a directory to browse.

When adding a recipe, add its row to this table and use those five headings;
`make skill-check` rejects an unlisted page or a missing section.

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

An existing project follows the same rule: find its pinned tag in
`project-manifest.yaml`, `pyproject.toml`, or `package.json`, and check out
that exact tag. Never read a newer checkout while writing code for an older
pin.

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

Apply these tests in order; the first answer wins:

1. Does a playbook package already provide it? → **Reuse.**
2. Does an existing setting, registry, router seam, or extension point change
   it? → **Configure.**
3. Is it specific to this product's domain? → **Create.**
4. None of the above, and the change is genuinely required? → **Vendor**, with
   a written reason and provenance.

Read `reference/decision-guide.md` only when a capability is ambiguous or
vendoring is on the table. Do not read it end to end as a prerequisite.

Record the decisions in `project-manifest.yaml` (`decisions:`), including why
the profile was chosen and every vendor entry.

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

The initial scaffold is the one task that needs the full composition
references. After the shell exists, do not re-read them for every feature;
open the one use-case page that matches the capability.

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

For each capability after the shell exists, use the catalog above. Typical
additions map to one recipe each: permissions, settings, OIDC, pagination,
domain slice, frontend page, CRUD page, paged list, MCP tool, RAG stage.

## Step 5 — Build one real vertical slice

Before breadth, prove every seam with one domain capability end to end:
table + migration → permission code → service → API endpoint → frontend
page → route/nav → translation → tests. Read
`reference/use-cases/add-backend-domain-slice.md` and
`reference/use-cases/add-frontend-page.md` for the two halves; do not read the
whole composition references again.

Keep the demo Items surface until the slice works; it is harmless, and
deleting it from a composed install is not a supported seam.

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
6. If the gap is a missing gate, a repeated workaround, or a missing/stale
   use-case page, add it to `reference/use-cases/` or to the playbook's tests
   so the next project inherits the fix.

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

Start with one use-case page. The files below are deep dives; open only the
section a recipe links to, or the two composition files during the initial
scaffold.

| File | Use |
|---|---|
| `reference/use-cases/` | One-task recipes — the default reading path |
| `reference/decision-guide.md` | Reuse / configure / create / vendor, with the exact seams |
| `reference/backend-composition.md` | Initial backend scaffold: settings, app factory, permissions, migrations, domain, MCP tools |
| `reference/frontend-composition.md` | Initial frontend scaffold: install model, shell, routes, i18n, Tailwind, proxy |
| `reference/quality-gates.md` | The production checklist and its evidence |
| `reference/upstream-loop.md` | Improving the playbook after a project finds a gap |
