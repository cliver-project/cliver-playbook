# Releasing cliver-playbook

Every backend distribution and every frontend package shares one version.
Pushing a `vX.Y.Z` tag releases the complete set; no module is released on its
own.

## Cut a release

1. Bump every manifest and both lockfiles:
   ```sh
   make version-set VERSION=0.2.0
   ```
   This rewrites the four backend `pyproject.toml` files (including the
   `==` pins between them), the workspace `package.json`, and every frontend
   package and dev shell, then runs `uv lock` and `pnpm install
   --lockfile-only`.
2. Verify the tree before tagging (a tag is immutable once published):
   ```sh
   make check
   make verify-reference
   make release-check
   git diff                     # review the version bump and lockfiles
   ```
3. Commit the bump, then tag and push:
   ```sh
   git add -A
   git commit -m "release: v0.2.0"
   git tag v0.2.0
   git push origin main
   git push origin v0.2.0
   ```
4. The `Release` workflow (`.github/workflows/release.yml`) runs on the tag:
   it verifies that every manifest carries `0.2.0`, builds all four backend
   distributions, checks that each wheel and sdist carries the Apache-2.0
   license text, publishes them to PyPI in dependency order
   (`basic` → `user` → `rag` → `mcp`), and creates a GitHub release with the
   build artifacts.

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
| `cliver-playbook-app-basic` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi` |
| `cliver-playbook-app-user` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi` |
| `cliver-playbook-app-rag` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi` |
| `cliver-playbook-app-mcp` | `cliver-project` | `cliver-playbook` | `release.yml` | `pypi` |

The GitHub repository must be named `cliver-playbook` (PyPI matches the
repository name exactly). Create the `pypi` environment in the repository
settings; no secrets are stored in it. After the first successful upload, the
pending publisher becomes the project's normal trusted publisher.

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
    "cliver-playbook-app-basic": "github:cliver-project/cliver-playbook#v0.2.0&path:/packages/frontend/cliver-playbook-app-basic",
    "cliver-playbook-app-user": "github:cliver-project/cliver-playbook#v0.2.0&path:/packages/frontend/cliver-playbook-app-user"
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
  cliver-playbook-app-basic: "github:cliver-project/cliver-playbook#v0.2.0&path:/packages/frontend/cliver-playbook-app-basic"
  cliver-playbook-app-user: "github:cliver-project/cliver-playbook#v0.2.0&path:/packages/frontend/cliver-playbook-app-user"
  cliver-playbook-app-rag: "github:cliver-project/cliver-playbook#v0.2.0&path:/packages/frontend/cliver-playbook-app-rag"
  cliver-playbook-app-mcp: "github:cliver-project/cliver-playbook#v0.2.0&path:/packages/frontend/cliver-playbook-app-mcp"
```

Then run `pnpm install` and commit `pnpm-lock.yaml`. Upgrade by changing every
`#vX.Y.Z` in both files to the new tag and reinstalling. If the repository is
private, configure git credentials for pnpm (SSH or a token) before
installing.

The playbook workspace itself keeps using the local packages:
`linkWorkspacePackages: true` in `pnpm-workspace.yaml` links the copies whose
versions match, so development never reaches the registry or GitHub.

## What is intentionally not automated

- `make check` and `make verify-reference` run before the tag, not inside the
  release workflow: the reference smoke needs Docker and a PostgreSQL service,
  and a release should not start on a tree that was never verified locally.
- No npm publishing, no per-module versioning, and no release branches. Every
  release is one tag over the whole repository.
