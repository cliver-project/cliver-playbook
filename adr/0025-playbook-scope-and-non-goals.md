# ADR-0025: Playbook scope, seams and non-goals

**Status:** Accepted (2026-11-07).
**Context:** Coding agents can already generate a credible login page, a CRUD
screen or a RAG chat surface from a short prompt. The playbook cannot justify
itself by writing code faster, and should not try. Its durable value is four
things: repeated decisions made once instead of re-derived per project;
fixes that land once and propagate through versioned packages; compressed
context through the use-case skill; and a production baseline (identity,
RBAC, audit, governance, release) that a generated demo does not include.

That value disappears if the project becomes a framework, a code generator,
or a growing pile of code with no stronger contract than generated code. This
ADR fixes the boundary so future changes can be rejected on principle rather
than taste. It also records the conditions under which a capability should
stay local to a consumer instead of entering the library.

## Decision

1. **Composable packages and explicit seams, not application control flow.**
   The playbook may own cross-cutting infrastructure and provide hooks. It must
   not own an application's domain flow, route policy or business decisions. A
   consumer must be able to replace or bypass a behaviour through configuration,
   a registry or a documented seam without editing installed code. If a request
   needs a branch in a core flow, the answer is a new seam, not a new `if`.
2. **No deployment-specific values in code.** Hosts, URLs, credentials, tenant
   or project names and provider endpoints live in configuration or adapter
   options, with safe defaults and startup validation. A production host that a
   sandbox or proxy cannot override is a bug.
3. **Every capability has a real consumer and an exit path.** No speculative
   features. Add a capability only when a real consumer needs it, or when a
   second consumer is concrete and scheduled. Prefer extending an existing seam
   over adding a subsystem. A capability that cannot be removed or deprecated
   without breaking unrelated packages is too coupled.
4. **Contracts and tests are the product.** A change is not done without a test
   that fails if the behaviour regresses, a public contract (types, docs and a
   use-case recipe), and an upgrade path (version bump plus the documented
   smoke). A skill or document that describes behaviour is part of the product;
   if it is not validated against the code, it is a bug.
5. **Domain logic stays with the consumer.** The playbook owns cross-cutting
   infrastructure and reference slices only. Project-specific entities,
   workflows, prompts, reports, copy and page composition belong to the
   project. The demo `items` surface is an example, never a domain base.
6. **Adoption must stay cheaper than regeneration.** Every release keeps
   composition small (no per-project glue), keeps upgrades to a dependency bump
   plus the documented smoke, and keeps the use-case layer accurate. If
   adopting or upgrading the playbook costs more than generating fresh code,
   the playbook has failed even if its code is better.
7. **Fix upstream, not downstream.** A consumer workaround is a signal that a
   seam is missing. The fix goes into the playbook with a failing test and a
   release, not into vendored copies or per-project patches. Vendoring is an
   explicit, exceptional fork with recorded provenance.
8. **Keep the surface small; deletion is a feature.** Prefer removing or
   deprecating a capability over accumulating options. A new option needs a
   named consumer and a test; a new package needs a distinct concern that
   cannot live in an existing package. The playbook is read by agents and
   humans, and every added concept raises the adoption and context cost.

## Review questions

Before merging a capability, answer these in the change description:

1. Which consumer needs it now, and what happens if it is not added?
2. Is this a seam or a branch? Can a consumer override it without editing the
   playbook?
3. Would the same fix otherwise be repeated in more than one project?
4. What test fails if this regresses, and what contract tells an agent how to
   use it?
5. Does a consumer upgrade with a dependency bump and smoke, or must it read the
   diff and change domain code?
6. If this is the only consumer and no second one is planned, should this live
   in the project instead?

## Non-goals

- Being a full-stack framework or owning application control flow.
- Generating an application from a prompt, or replacing coding agents.
- Absorbing project-specific domain models, business workflows, prompts or
  copy.
- Hardcoding deployment endpoints or credentials.
- Supporting every provider through built-in adapters; the adapter seam is the
  extension point.
- Adding features with no consumer, or keeping options with no user.
- Shipping documentation or skills that are not validated against the code.

## Consequences

- Some requests are answered with "configure it locally" or "own it in the
  project". That is the boundary working, not a refusal to help.
- Hardcoded endpoints and credentials are treated as bugs, not shortcuts.
- The skill/use-case catalog and its validation are release-gated.
- The playbook stays small enough to read, compose and upgrade.
- The project is justified by repeated production needs, not by code volume; a
  single consumer with no second in sight is a signal to keep the capability
  local.

## Alternatives considered

- **No written scope, rely on taste:** rejected. Scope decisions then depend on
  who reviews the change, and the project drifts toward a framework one option
  at a time.
- **Become a framework with stronger opinions:** rejected. A framework owns
  control flow and makes every deviation a fork; it is the opposite of the
  seam-based composition the playbook sells.
- **Generate a fresh template per project instead of maintaining packages:**
  rejected for cross-cutting infrastructure, where fixes and audits would be
  repeated per project. Acceptable for domain code, which the playbook does not
  own.
