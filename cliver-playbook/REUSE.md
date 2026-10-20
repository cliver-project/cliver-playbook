# Reusing cliver-playbook

## Purpose

cliver-playbook is the engineering asset library behind a one-person project
workflow. It holds the cross-cutting infrastructure that every project would
otherwise rebuild: layered settings, database and Alembic mechanics, identity
and RBAC, the React application shell, i18n/theme, the RAG module, the MCP
surface, and the test/tooling conventions that keep them honest.

The library is consumed by new projects, not extended in place by them. A
project selects the capabilities it needs, composes the published packages,
and owns only its domain code. The playbook packages stay the source of truth
for the infrastructure (ADR-0015).

## Decision tree

Use the highest rung that satisfies the need:

1. **Compose a package** when the capability is cross-cutting infrastructure:
   settings, database/Alembic, auth/RBAC, i18n, theme, RAG, MCP, or the test
   harness. These are already parameterized and are expected to receive
   upstream fixes.
2. **Generate or copy** when the code is project-specific domain logic: an
   entity, a screen, a workflow, a report, a prompt. It may start from an
   example in the playbook, but the project owns it and may reshape it freely.
3. **Vendor** only when the project must deeply customize a playbook package
   and cannot express the change through configuration or an extension seam.
   Vendoring keeps the `cliver_playbook` namespace and records provenance; it
   is an explicit, opt-in fork, not the default.

If a change belongs to the infrastructure rather than the project, contribute
it to the playbook package instead of vendoring or copying it.

## Capability tiers

| Tier | Examples | Default strategy |
|------|----------|------------------|
| Tooling | Makefile targets, pytest/ruff/oxlint configuration, workspace layout | Copy once, then own it; project paths and commands differ |
| Cross-cutting infrastructure | settings, DB/Alembic, auth/RBAC, i18n, theme, RAG, MCP, test harness | Compose the published package |
| Product shell | React app shell, routing, providers, layout | Compose `cliver-playbook-app-basic`, add project routes/pages |
| Domain | entities, services, screens, report/export logic, prompts | Generate or copy; never treat the demo Items surface as the domain |
| Project workflow | assembly skills, manifest, release checks | Use the playbook tooling, record the project manifest |

## Modes

**Compose by default.** A project lists the packages it uses and pins the
playbook revision; it does not copy their source.

- `compose` — install the published packages. Recommended and the default.
- `vendor` — copy a package's `src/cliver_playbook` subtree and its `alembic/`
  chain into the project while preserving the `cliver_playbook` namespace.
  Do not rename the package by hand. The project imports the vendored module
  path and owns the copy.
- `generate` — create project-specific domain code only. It is not a way to
  obtain playbook infrastructure.

Do not mix compose and vendor for the same package. A vendored package replaces
the installed dependency for that import path; the project manifest must say
which one is in use.

## Provenance

Every vendored tree carries `vendor/FORKED_FROM.md` with all of the following:

```markdown
# Forked from cliver-playbook

- Source repository: https://github.com/cliver-project/mcp_x
- Revision: vX.Y.Z (commit <sha>)
- Source path: packages/backend/cliver-playbook-app-<name>/src/cliver_playbook
- Target path: vendor/cliver_playbook
- Date: YYYY-MM-DD
- Local changes: <list, or "none yet">
- Upgrade policy: no upstream sync; compare against later playbook tags manually.
```

The revision is the exact tag or commit that was copied, never `main`. When a
later playbook release changes the vendored package, record the comparison and
the decision to merge or decline it in the same file.

## Versioning

- **One version for the whole library.** Every backend distribution and every
  frontend package shares the same version number. A release either publishes
  the complete set or nothing.
- **Consume by tag or commit.** New projects pin `playbook.revision` to a
  release tag such as `v0.2.0`; they never track `main`. The project manifest
  validator rejects `main`/`HEAD` as the only revision.
- **Backend packages are published to PyPI.** A `vX.Y.Z` tag triggers the
  release workflow, which verifies that every manifest carries `X.Y.Z` and
  publishes the four backend distributions.
- **Frontend packages are consumed from the git tag.** They are private
  source packages and are not published to npm. A project references the
  package by repository, tag and path, for example:
  ```json
  "cliver-playbook-app-basic": "github:cliver-project/mcp_x#v0.2.0&path:/packages/frontend/cliver-playbook-app-basic"
  ```
  pnpm resolves the tag and the monorepo subdirectory in one reference. Pin
  the tag in `pnpm-lock.yaml` as usual.
- **Editable workspace installs are for playbook development only.** A
  consuming project installs tagged artifacts; the editable `uv`/`pnpm`
  workspace is how maintainers work on the playbook itself.
- **Commit lockfiles.** `uv.lock` and `pnpm-lock.yaml` are part of the project
  and must be reviewed and committed with the dependency change.

## Not reusable as-is

- The demo Items API, pages and navigation. They exist to prove the stack, not
  to define a product.
- Authentication and authorization policy assumptions: single-tenant data,
  the shipped permission codes, and the default OAuth/OIDC provider wiring.
- Deployment-specific defaults: local hostnames and ports, the compose
  PostgreSQL credentials, and any checked-in development URLs.
- Domain models, screens and copy that assume a different product.
- Code that would need a different namespace. Vendoring preserves
  `cliver_playbook`; a namespace rename is a separate, import-aware codemod.

## New-project checklist

1. Choose capabilities: `minimal`, `web`, `rag`, or `mcp`.
2. Choose a mode; default to `compose`. Pick `vendor` only with a concrete
   reason, and never mix modes for one package.
3. Record `project-manifest.yaml` with the playbook source, the release tag,
   the selected backend/frontend packages, and any vendored trees.
4. Validate the manifest:
   `uv run python scripts/validate_project_manifest.py project-manifest.yaml`.
5. Assemble with the `assemble-project` skill, then wire project routes,
   settings and migrations without editing the playbook packages.
6. Run the project's lint, tests and frontend build, then boot it against a
   scratch database and hit its health endpoint.
7. Review the diff: project code only, tagged dependencies, committed
   lockfiles, and `FORKED_FROM.md` for every vendored tree.
