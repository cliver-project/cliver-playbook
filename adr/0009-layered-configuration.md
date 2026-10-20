# ADR-0009: Layered configuration with a checked-in app.yaml

**Status:** Accepted (2026-10-15; write-up 2026-10-17).
**Context:** Configuration started as a flat set of environment variables read by a
`BaseSettings` class, which is fine until a project needs a *provider registry*, a
default that is a composed value, or a comment explaining why a setting exists. `.env`
files give no structure and no comments reach the deployed artifact; environment
variables alone make the defaults invisible. Meanwhile a per-package config file
temptation existed once the code became installable packages.

## Decision

1. **Three layers, one precedence order** (highest first): **environment variables →
   `.env` → `app.yaml` → field defaults in the `Settings` class**. Every variable keeps
   a working default, so a fresh clone runs with no configuration at all.

2. **`app.yaml` is checked in and holds no secrets.** It carries the decisions a
   deployment should see in review: defaults, provider presets, and the comments that
   explain them. Secrets live in the environment or the gitignored `.env`; the
   repository ships only `.env.example` with placeholders.

3. **Keys are bare field names** — `database_url`, not `CLIVER_DATABASE_URL` — because
   the `CLIVER_` prefix belongs to the environment layer. Nested models are written as
   YAML mappings (`oidc.providers.google.*`) and overridden from the environment with
   the `__` delimiter (`CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_SECRET`).

4. **The file is Jinja2-rendered before it is parsed** (sandboxed, strict undefined),
   so a value can be composed from parts — the bundled `env(name, default)` helper
   reads the process environment, then `.env`, then the default, and a call with no
   default makes that variable **required**: startup fails with its name rather than
   running with a wrong value. This keeps "compose the DSN from parts" out of Python.

5. **The `Settings` class is the single structure authority.** Layer order is declared
   once (`settings_customise_sources`), the YAML path is resolved per instantiation
   (so an override variable is honoured), and validation lives in the model:
   cross-field rules (an enabled provider must carry a client id, a secret, and either
   an issuer or all three explicit endpoints), normalization (case-folding provider
   keys so a YAML preset and an environment override merge into one entry), and a
   `str`-typed field with a joining validator for values the environment layer would
   otherwise try to parse as JSON.

6. **Unknown keys are ignored** (`extra="ignore"`), which is deliberate — the same
   `Settings` is instantiated against test fixtures and deployment files with extra
   keys — but it converts a typo into silence, so the class docstring and the example
   file both say it.

7. **Configuration is discovered by walking up from the working directory** to the
   nearest directory containing `app.yaml` or `.env`, with an environment variable to
   point at a file explicitly. The predecessor anchored paths at `__file__`, which was
   correct for source trees and **wrong the moment the code is installed** into a
   virtualenv's `site-packages`.

8. **Instantiating settings is not an import side effect** — the runtime carries the
   mechanism (ADR-0016), so importing a package reads no file and creates no engine.

## Consequences

- A deployed artifact carries `app.yaml`; changing a default is a reviewed diff rather
  than an undocumented environment variable. Comment lines and provider blocks live
  next to the values they explain.
- Environment variables can add or override, but **cannot remove** a preset — the merge
  is additive. Removing one is not a supported operation; it is disabled instead.
  A preset that is edited in place can be overridden key by key from the environment.
- Renaming or removing a setting is a migration event: `extra="ignore"` means old
  names fail silently. The flat OIDC variables that became the nested block are the
  precedent, and the example file carries the migration note.
- A proxy or container deployment must restart the app after editing `app.yaml`
  (dev-mode auto-reload does not watch a file outside the source tree).

## Alternatives considered

- **`.env` only**: rejected — no structure, no nested models, no comments that survive,
  and the defaults would be invisible to a reviewer.
- **Environment variables only** (twelve-factor orthodoxy): rejected for the same
  reason plus one specific to this project: a *registry* of providers with per-provider
  fields is unreadable as twenty environment variables.
- **One config file per package**: rejected — a deployed application has one
  configuration; per-package files would need a merge order, and their relative
  precedence would be a new class of bug. Packages instead *contribute fields* to the
  one `Settings` subclass chain.
- **A config service or database-stored settings**: rejected — configuration and
  secrets in the same place as application data invites accidental exposure, and it
  adds a bootstrap dependency to every start.
- **Validating configuration at first use instead of startup**: rejected — a bad
  provider block should stop the process, not surface as a failed login days later.
