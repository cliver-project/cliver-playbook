# The upstream loop

Each project is also a test of the playbook. A gap found while assembling a
project is the cheapest evidence the playbook will ever get; fixing it there
raises the floor for every later project. A workaround that stays only in the
project lowers the next project's starting quality.

The rule: **fix the playbook, then bump the project's pin.** Do not patch an
installed package, and do not let a fork become the project's private
infrastructure.

## Triage the gap

| Symptom | Disposition |
|---|---|
| The capability exists but is undiscoverable or undocumented | Documentation fix in the owning package's README, `REUSE.md`, or this skill |
| A step fails on the documented path | Bug in the playbook; fix with a regression test |
| A repeated manual workaround in every project | Missing seam or missing default; add the seam/default and a test |
| A gate the project needed that this skill does not list | Add it to `reference/quality-gates.md`; add an automated check if one is possible |
| Product-specific behavior | Not upstream; keep it in the project |
| A missing model capability | Add it to cliver-core, not to the playbook package (model access rule) |

Before writing code, answer: would a second, unrelated project need this? If
yes, it is upstream material. If only this product needs it, it belongs in the
project.

## Reproduce against the pinned tag

`var/playbook` is a shallow clone at the project's tag and is gitignored. Do
not develop a fix in it. Make a full checkout outside the project's tracked
tree:

```sh
git clone https://github.com/cliver-project/cliver-playbook /tmp/playbook
cd /tmp/playbook
git checkout 0.1.0
git switch -c fix/<short-name>
```

Confirm the bug exists at that tag. If it only exists on `main`, it is not
this project's gap; report it separately.

## Write the failing test first

Reproduce the gap as a test in the owning package, at the lowest level that
can express it. A seam that cannot be tested in the package is not ready to
ship.

- Backend behavior: `packages/backend/<package>/tests/`.
- Frontend behavior: the package's `dev/` shell exercises typecheck, lint, and
  build; add a component/unit test only if the package already has a test
  harness, otherwise encode the behavior in the type system or the dev shell.
- Tooling and scripts: the repository's script tests; `make check` must cover
  them.
- Reference wiring: `make verify-reference` is the end-to-end check that the
  packages compose into a running app. A wiring bug needs a change there or in
  the reference app, not only in a unit test.

Run the test, watch it fail for the expected reason, then implement the
minimum that passes. Keep the package's existing conventions: ruff line length
100 and target py312; `asyncio_mode = "auto"`; imports pinned first-party for
`cliver_playbook`.

## Fix at the right layer

- Prefer a setting, registry entry, or documented extension point over a new
  branch in core code.
- A new setting needs: a field with a safe default, docs in the package README,
  an entry in `app.yaml` if operators set it, and a test that the default
  preserves current behavior.
- A new permission code belongs to the package that owns the resource; do not
  add project-domain codes to the playbook.
- A new runtime-settings section must be registered by the owning package and
  documented with its env var and apply semantics.
- A behavior change that affects the public contract needs an ADR. ADRs are
  append-only: amend an existing one by appending, never by rewriting.
- Never add a company name, client name, real URL, or credential to a package,
  test, example, or ADR.

## Verify the whole playbook

```sh
make check             # backend lint/tests, frontend checks, script checks
make verify-reference  # the composed reference app: DB, migrations, API, UI build
```

Both must pass from a clean tree. `make check` needs PostgreSQL
(`make db-up`); a skipped database test is not a pass. If the change touches
frontend sources, also build the affected dev shells and check their CSS
sentinels (`reference/quality-gates.md`, Gate 6).

Update the docs in the same change:

- The package README (usage and constraints).
- `REUSE.md` if the disposition in the capability matrix changes.
- `reference/decision-guide.md` in this skill if a seam is added or an old
  answer becomes wrong.
- The ADR index in the playbook README if an ADR was added.

## Release

Releases are cut by a maintainer; a project author does not push a tag.

```sh
make release VERSION=X.Y.Z
```

The release target refuses an unbumped version, aligns every backend pin and
frontend reference, runs the checks, commits, tags `X.Y.Z` (no `v` prefix),
and pushes. The tag triggers publication of the four backend distributions in
dependency order and creates the GitHub release. See `docs/releasing.md` in
the playbook for the trusted-publisher setup and the frontend git-dependency
form.

After the tag exists:

1. Update every project pin: backend `==X.Y.Z`, frontend `#X.Y.Z` in
   `package.json` and every `overrides` entry, and `playbook.revision` in
   `project-manifest.yaml`.
2. Reinstall: `uv sync` and `pnpm install`; commit both lockfiles.
3. Rerun every gate in `reference/quality-gates.md`. A version bump is not a
   no-op: run the migrations from empty, boot, and rebuild the frontend.
4. Record the bump in the project's README or changelog.

Until the tag is published, keep the project on the old pin. Do not point the
project at a branch, a commit on `main`, or a local checkout to get an
unreleased fix — that breaks reproducibility and hides the missing release.

## When vendoring is the answer

Only after the seam analysis in `reference/decision-guide.md` says no
extension point can express the change. Use the vendoring script so the
namespace stays intact:

```sh
python3 var/playbook/scripts/vendor_package.py \
  --package cliver-playbook-app-mcp --target . --apply
```

Then:

- Remove the vendored package from the project's dependencies (never mix
  compose and vendor for one package).
- Verify the import resolves under `vendor/`:
  `python -c "import cliver_playbook.app.mcp as m; print(m.__file__)"`.
- Record provenance in `vendor/FORKED_FROM.md` and in the manifest's
  `vendored:` entries, with the tag and the reason.
- Comment every local change with `PROJECT FORK:` and the reason.
- Treat every future playbook release as a manual merge: diff the vendored
  tree against the new tag and reapply the changes.

Vendoring is a bounded exception, not the start of a private library. If the
fork grows beyond the original reason, propose the change upstream instead.

## Feed the ratchet

For each project, add at least one of:

- A regression test in the package that now covers the gap.
- A gate in `reference/quality-gates.md` that would have caught it.
- A seam documented in `reference/decision-guide.md` that removes the
  workaround.
- A note in the package README that makes the constraint discoverable.

These are the artifacts that make the next project start faster and at a
higher quality. A fix that exists only in one project does not compound.

## Report template

When handing a gap to the playbook maintainer:

```text
Affected playbook tag: 0.1.0
Package: cliver-playbook-app-<name>
Expected: <the behavior a project needs>
Actual: <what happens, with the command and the error>
Reproduction: <minimal steps from a clean checkout>
Proposed seam: <setting / registry / router / test helper / doc>
Project impact: <what the project does until a release exists>
```

Keep the reproduction free of project names, client data, and secrets. Use a
synthetic example that exercises the same code path.
