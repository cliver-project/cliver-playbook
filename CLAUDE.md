# Project rules

`cliver-playbook` is a platform repository: composable packages, the decisions
behind them, and the skill that assembles them. It is not an application and not
a code generator. Read `adr/0025-playbook-scope-and-non-goals.md` before adding
or changing a capability. The short enforcement list:

- **Seams, not control flow.** Packages and documented extension points only; a
  consumer must be able to replace or bypass a behaviour without editing
  installed code.
- **No deployment-specific values.** Hosts, URLs, credentials, tenant/project
  names and provider endpoints are configuration with safe defaults and startup
  validation.
- **A real consumer, and an exit path.** No speculative features; prefer
  extending an existing seam over adding a subsystem, and keep every capability
  removable.
- **Contracts and tests are the feature.** A regression test, a public contract
  and an upgrade path are part of "done"; validated use-case docs are product,
  not optional documentation.
- **Domain logic stays with the consumer.** The playbook owns infrastructure and
  reference slices, never a project's entities, workflows or copy.
- **Adoption must stay cheaper than regeneration.** If composing or upgrading
  costs more than generating fresh code, the playbook has failed.
- **Fix upstream.** A consumer workaround means a seam is missing; fix it in the
  package with a failing test and a release.
- **Keep the surface small.** Deletion and deprecation are valid outcomes.

When the README, `REUSE.md` and the ADRs disagree, the latest accepted ADR wins
and the other document is a bug. Repository conventions (English-only code,
comments and docs; no secrets, client names or real URLs) are in
`README.md#conventions`.
