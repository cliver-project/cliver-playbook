# Releasing cliver-playbook

Every backend distribution and every frontend package shares one version.
Pushing a `X.Y.Z` tag (named exactly the version) releases the complete set; no module is released on its
own.

## Cut a release

One target cuts the release:

```sh
make release VERSION=0.2.0
```

`VERSION` is optional. The target refuses to run when the shared version is
not bumped past the latest release tag, and tells you to bump first. Either pass
`VERSION` to let the release script align everything, or bump and commit it
yourself, then run `make release`:

```sh
make version-set VERSION=0.2.0
git add -A && git commit -m "release: 0.2.0"
make release
```

Every path checks that the four backend `pyproject.toml` files, the workspace
`package.json`, all frontend packages and dev shells, and every inter-module
dependency pin (`==0.2.0` backend pins and frontend sibling versions) agree
on one version. With `VERSION`, the script rewrites them all and refreshes
`uv.lock` and `pnpm-lock.yaml`.

The target then:

1. Runs `make check`, `make verify-reference`, and `make release-check`
   (a tag is immutable once published).
2. Commits the version bump, but only if the pending changes are version
   manifests or lockfiles; any other change stops the release.
3. Creates the annotated tag `0.2.0` (the tag name is the version).
4. Pushes the current branch and the tag to `origin`; the tag triggers the
   `Release` workflow, which verifies that every manifest carries `0.2.0`,
   builds all four backend distributions, checks that each wheel and sdist
   carries the Apache-2.0 license text, publishes them to PyPI in dependency
   order (`basic` → `user` → `rag` → `mcp`), and creates a GitHub release
   with the build artifacts.

Preview without changing anything:

```sh
make release DRY_RUN=1
```

After a partial failure, re-run `make release`: an existing local tag on HEAD
is reused and the push is retried. For a recovery run whose checks already
passed, run `python3 scripts/release.py --skip-checks`; add `--no-push` to
keep the tag local.

Each backend package directory contains a copy of the root `LICENSE`
(`license-files` in its `pyproject.toml`), because a wheel built from a
package directory cannot reach the repository root and Apache-2.0 requires
the license text to travel with the distribution. `make release-check` runs
the same artifact check locally.

`uv publish --check-url` makes the publish step idempotent: files already on
PyPI are skipped, so a re-run after a partial failure is safe.

## PyPI trusted publishing (one-time setup)

The workflow publishes with PyPI trusted publishing (OIDC), not an API token.
Before the first release, add a **pending trusted publisher** on PyPI for each
project:

| PyPI project | Owner | Repository | Workflow | Environment |
|---|---|---|---|---|
| `cliver-playbook-app-basic` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi-basic` |
| `cliver-playbook-app-user` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi-user` |
| `cliver-playbook-app-rag` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi-rag` |
| `cliver-playbook-app-mcp` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi-mcp` |

The GitHub repository must be named `cliver-playbook` (PyPI matches the
repository name exactly). Create the four environments in the repository
settings; no secrets are stored in them.

Each project needs its own environment because PyPI identifies a *pending*
trusted publisher by the tuple (owner, repository, workflow, environment).
Registering the same tuple for a second project fails with "A pending trusted
publisher matching this configuration has already been registered for a
different project name." Distinct environments make the four pending
publishers legal; the workflow runs one publish job per environment in
dependency order. After the first successful upload, each pending publisher
becomes that project's normal trusted publisher.

### First release with four projects

PyPI allows at most three pending trusted publishers per account at once.
Register `pypi-basic`, `pypi-user` and `pypi-rag` first, then cut the release.
The workflow builds and publishes those three; `publish-mcp` fails because
its pending publisher does not exist yet, so no GitHub release is created.
The three pending publishers have now become normal publishers and no longer
occupy the pending slots. Register the fourth pending publisher
(`cliver-playbook-app-mcp`, environment `pypi-mcp`), then re-run the failed
jobs of the same workflow run: `publish-mcp` creates the project, the
version's already-published files are skipped by `--check-url`, and the
GitHub release job runs. Later releases publish all four in one pass.

## Frontend packages

Frontend packages are not published to npm. They are consumed from the same
release tag as TypeScript source, so the tag, not a registry, is the version
boundary.

A consuming project installs the packages it selected as git dependencies.
Because the library packages depend on each other, pnpm must resolve those
sibling dependencies from the same tag as well. In the consuming project:

`package.json`:

```json
{
  "dependencies": {
    "cliver-playbook-app-basic": "github:cliver-project/cliver-playbook#0.2.0&path:/packages/frontend/cliver-playbook-app-basic",
    "cliver-playbook-app-user": "github:cliver-project/cliver-playbook#0.2.0&path:/packages/frontend/cliver-playbook-app-user"
  }
}
```

`pnpm-workspace.yaml`:

```yaml
packages: []

# Git dependencies are "exotic"; pnpm blocks them in subdependencies by
# default. The overrides point every playbook package at the same tag.
blockExoticSubdeps: false
overrides:
  cliver-playbook-app-basic: "github:cliver-project/cliver-playbook#0.2.0&path:/packages/frontend/cliver-playbook-app-basic"
  cliver-playbook-app-user: "github:cliver-project/cliver-playbook#0.2.0&path:/packages/frontend/cliver-playbook-app-user"
  cliver-playbook-app-rag: "github:cliver-project/cliver-playbook#0.2.0&path:/packages/frontend/cliver-playbook-app-rag"
  cliver-playbook-app-mcp: "github:cliver-project/cliver-playbook#0.2.0&path:/packages/frontend/cliver-playbook-app-mcp"
```

Then run `pnpm install` and commit `pnpm-lock.yaml`. Upgrade by changing every
`#X.Y.Z` in both files to the new tag and reinstalling. If the repository is
private, configure git credentials for pnpm (SSH or a token) before
installing.

The playbook workspace itself keeps using the local packages:
`linkWorkspacePackages: true` in `pnpm-workspace.yaml` links the copies whose
versions match, so development never reaches the registry or GitHub.

## Assembly skill

The skill is published independently of the packages and is not part of the
`X.Y.Z` release. There is no tag and no release step: the default branch is the
distribution. `npx skills add` clones `main` and installs the current
`SKILL.md`; `npx skills update` re-fetches it. No npm package is published.

```sh
# Installs the current skill from the default branch
npx skills add cliver-project/cliver-playbook --skill cliver-playbook-assemble-project

# For an exact copy, pin a commit instead
npx skills add https://github.com/cliver-project/cliver-playbook/tree/<SHA>/skills/cliver-playbook-assemble-project
```

The skill describes the latest guidance; it has no version of its own and does
not need to match the tag a project pins. `.github/workflows/skills-check.yml`
only validates it: on a push to `main` or a pull request that touches
`skills/**` or the validator scripts, it runs
`scripts/validate_skill.py`. Invalid content never reaches the default branch.
`make skill-check` runs the same checks locally.

## What is intentionally not automated

- `make check` and `make verify-reference` run before the tag, not inside the
  release workflow: the reference smoke needs Docker and a PostgreSQL service,
  and a release should not start on a tree that was never verified locally.
- No npm publishing, no per-module versioning, and no release branches. Every
  package release is one tag over the whole repository. The assembly skill has
  no release of its own: it is served from the default branch and only
  validated in CI.
