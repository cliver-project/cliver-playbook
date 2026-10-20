# ADR-0021: Superuser wildcard and module-owned runtime settings

**Status:** Accepted (2026-10-19).
**Context:** Two administrator needs exposed gaps in the identity and
configuration design. First, the seeded `admin` role enumerated the permission
catalog at migration time, so codes registered later by a composing package
(`mcp:*`, `rag:*`) never reached an existing administrator. Second, every
operator knob lived in the environment, `.env`, or the checked-in `app.yaml`;
changing a retrieval budget or a lockout threshold meant editing a file and
restarting, and the administrator had no application-level settings surface.

The settings surface must not become one giant identity-owned schema: the RAG
package owns its pipeline stages, chunking defaults, retrieval budgets, and the
cliver-core model bindings, and a package that does not know those fields must
not be the place that validates or applies them.

## Decision

1. **`*` is the superuser wildcard permission.** `Viewer.has(code)` returns
   true when the viewer holds `*` or the requested code. The seeded `admin`
   role is pinned to exactly `["*"]`; a role set containing `*` normalizes to
   `["*"]`. Migration `0002_superuser_permission` converts databases seeded the
   old way, and fresh installs get the wildcard from the `0001` seed.
2. **Only a wildcard holder may grant or touch the wildcard.** Creating a role
   with `*`, adding `*` to an existing role, editing or deleting a role whose
   current set contains `*`, and narrowing the system `admin` role are all
   rejected for callers without `*` — even if they hold `role:manage`. The
   checks live in `user.services.roles`, so in-process callers get the same
   boundary as the HTTP API (`actor=None` is not a wildcard holder).
3. **New permissions need no migration.** Because `*` is evaluated at request
   time, codes registered by a package after the role was created are covered
   automatically. The administrator never loses access to a newly installed
   surface.
4. **Runtime settings are module-owned sections.** A package registers a
   `SettingsSection(key, title, description, fields, read, apply)` with
   `basic.runtime_settings.register_settings_section()` at import time. The
   section declares its fields, validates the full resulting state, and mutates
   the live Settings instance. The identity package's admin router owns only
   HTTP, authorization, persistence and audit; it never interprets section
   fields. Registered today: `user` (identity policy) and `rag` (stages,
   chunk sizing, retrieval, reranking, upload cap, and the cliver-core
   purpose bindings for chat, embeddings, and reranking).
5. **The framework lives in `basic`; the HTTP surface lives in `user`.** The
   registry, field descriptions, validation helpers, persistence loader and
   lifespan overlay are in `cliver-playbook-app-basic`, which has no business
   dependencies. Any composed application can expose the same surface by
   installing the identity package — `GET /api/v1/admin/settings`,
   `GET/PUT/DELETE /api/v1/admin/settings/{section}`.
6. **Precedence is environment > `.env` > persisted overrides > `app.yaml` >
   defaults.** At startup pydantic-settings resolves the first, second,
   fourth and fifth layers into the bound Settings instance; the lifespan then
   applies persisted overrides on top. A field explicitly set by the
   environment or `.env` is therefore read-only in the UI and rejected on
   write: the environment would win at the next restart anyway. Reset deletes
   the stored row and restores the startup baseline, which already includes
   the environment and `.env` values.
7. **Secrets are write-only.** A `secret=True` field never returns its value;
   the description reports only *configured* / *not configured*. The API
   accepts a replacement and persists it in the section row, so a model
   credential can be configured in the UI. If the field names an `env_var` and
   the environment or `.env` sets it, that value wins and the field becomes
   read-only — a deployment can still keep credentials out of the database.
   Audit detail masks secret values.
8. **Persistence is one row per section.** `app_settings(section PRIMARY KEY,
   values JSONB, updated_by, updated_at)` lives in the basic migration chain.
   The row stores only fields the administrator changed, so a later default
   change in code still reaches untouched fields. Partial updates merge; a
   stored unknown field is ignored on load, while an unknown field in a write
   request is a 400. There is no foreign key to users (basic cannot depend on
   the identity package); `updated_by` is informational.
9. **Validation precedes mutation.** Each section builds a Pydantic model from
   the current values plus the request and only then writes to
   `settings`/`settings.rag` in place. A rejected update leaves the live
   configuration and the stored row untouched, and dependencies that captured
   the Settings object see the accepted values on the next request. RAG stage
   choices are read from the live registries, so a newly installed
   implementation appears without a frontend or settings change.
10. **The startup overlay is best effort.** Each application's lifespan calls
    `load_persisted_settings()` before serving. A missing `app_settings` table
    (migrations not yet applied) is a warning; any other read failure and any
    malformed section row is logged and skipped. Configuration is an
    optimization at this point, never a reason to refuse to serve.
11. **Changes are audited.** `PUT` writes `admin.settings.update` and `DELETE`
    writes `admin.settings.reset`, both targeting `settings:<section>` and
    committed in the same transaction as the row change. Authorization is
    `settings:read` for inspection and `settings:manage` for change/reset; the
    seeded administrator passes through `*`, and a narrower operator role can
    be granted just these two codes.
12. **The UI is schema-driven.** The admin settings page renders every
    registered section from the description payload: enums become selects,
    numbers carry the declared bounds, secrets show a configured badge and a
    write-only password input (masked and read-only when the environment
    manages them), environment-managed fields are read-only with a source
    badge, and reset asks for confirmation. Adding a field is a backend-only change in its
    owning package. Section copy is translated by a shared
    `settingsSections.<key>` locale namespace; the owning frontend package
    ships those entries and the server's English string is the fallback, so
    an untranslated section still renders. The roles page treats `*` as an
    all-or-nothing choice and offers no edit/delete actions on wildcard roles
    to non-wildcard administrators.

## Why

- One trust decision ("this viewer is a superuser") instead of re-seeding
  role bindings every time a package adds a permission.
- Settings changes are immediate, audited, and reversible without editing a
  checked-in file or restarting the process, while environment-controlled
  deployments keep their authority.
- Ownership follows knowledge: only RAG can say which stages exist and what a
  valid chunk configuration is; the identity package stays a transport and
  audit layer. A future package adds a section without touching either the
  basic framework or the identity router.
- The wildcard keeps the blast radius explicit: an administrator can change
  policy, and — for sections that declare them — model credentials, without
  editing a file or restarting. A deployment that wants credentials outside
  the database pins them in the environment, which wins and locks the field.

## Alternatives considered

- **Seed the admin role with every code and migrate on package install.**
  Rejected: migrations would need to know about packages installed later, and
  already-seeded databases would still drift. The wildcard is evaluated at
  request time instead.
- **Give each module its own `/api/v1/<module>/settings` endpoint.** Rejected:
  fragmented authorization, audit and UI, and the administrator would have to
  discover endpoints. One registry-backed surface delegates to the same
  owners.
- **A typed column per setting or a table per section.** Rejected: every new
  knob would need a migration. A JSONB document per section keeps the schema
  stable while each owner validates its own shape.
- **Rebuild the Settings instance and engine after a change.** Rejected:
  in-place mutation keeps every existing reference (request dependencies,
  stage implementations) valid and avoids tearing down the connection pool.
- **Keep secrets environment-only.** The initial reading of this ADR did.
  Rejected once the cliver-core bindings moved into the settings surface: an
  operator cannot configure or rotate a per-purpose model credential from the
  UI, and each change needs a restart. Write-only storage, audit redaction,
  and the environment override keep the exposure bounded while allowing the
  database-backed flow.

## Non-goals

- Editing bootstrap credentials that are not section fields: `secret_key`,
  the initial admin password, OIDC client secrets, and the database URL.
  Model credentials declared by a section are editable but write-only.
- Per-user or multi-tenant settings; settings are process-wide.
- Versioned settings history or rollback beyond the audit trail (which records
  the requested change, not a full before-image).
- Settings that are consumed only at construction time (engine, middleware,
  secret derivation); owners expose only values read per request.
- Hot-reloading `app.yaml`, the environment, or `.env`.

## Risks

- **A single compromised administrator session is total.** Mitigated by the
  wildcard-role guards, the immutable system `admin` role, and audit rows for
  changes; it is not mitigated against an attacker who already holds `*`.
- **In-place updates are invisible to code that cached a value at startup.**
  Section owners must expose only fields their consumers read per request;
  this is a review rule, not something the framework can detect.
- **A database that is unavailable at startup silently serves static
  configuration.** The warning is logged and the settings page still reports
  the persisted source, but an operator may briefly see defaults. It is the
  deliberate trade for never failing startup.
- **A persisted secret sits in the `app_settings` row in plaintext.** The
  database is the trust boundary, exactly as it is for other application
  data. The API never returns it and the audit log masks it; a deployment that
  will not accept plaintext at rest pins the value in the environment, which
  overrides the row and makes the field read-only.
- **A compromised `*` holder can rotate model credentials.** This is inherent
  to an in-app credential surface. The wildcard-role guards and the audit
  trail bound who can do it and record when; they cannot prevent it.
- **A settings write validates against the live registries.** If a deployment
  removes a stage implementation while a stored override still names it, the
  startup overlay logs and skips that section rather than taking the process
  down; the UI then shows the static configuration.
