# ADR-0002: Fixed `app` package name and the three-token rename surface

**Status:** Accepted (2026-10-15)
**Context:** Templates are copied into new projects by skills. Copy-merge only works
if the integration surface is predictable.

## Decision

1. **The Python package in every template is `app/` and is never renamed.**
2. Project identity lives in exactly **three token variants**, all renamed mechanically
   when a new project is bootstrapped from the scaffold:

   | Token        | Used for                                              |
   |--------------|-------------------------------------------------------|
   | `cliver_app` | project ids: pyproject name, compose project/db name, test db name |
   | `cliver-app` | display: package.json name, index.html title, FastAPI title, header brand |
   | `CLIVER_`    | environment prefix for all settings                    |

3. Skills ship the exact `grep`/`sed` commands; the rename is three passes plus a
   verification grep for leftovers. UI-visible brand text additionally flows through
   i18n keys (`app.title`), so localization does not require touching components.

## Why the package stays `app`

Later templates (user-management, mcp-server) ship delta files that import
`app.auth.tokens`, `app.models.entities`, `app.core.config`. If each project renamed
the package, every drop-in would need import rewrites and the copy manifests would
describe file moves instead of file copies. `app` is short, non-branded, and matches
the CraftForge convention the scaffold derives from.

## Non-goals

- No copier/cookiecutter variable substitution — plain files plus documented rename
  commands. Templating engines add a build step to every consumer for zero gain at
  this scale.
- Internal storage keys (`cliver-theme` for theming, `i18nextLng` for language) are
  fixed and NOT part of the rename surface; they are per-browser, not per-deployment.
