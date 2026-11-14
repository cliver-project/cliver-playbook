# ADR-0026: AI-native project scaffold and contracts

**Status:** Accepted (2026-11-14).
**Context:** Every new project in this workspace is an AI-native application.
The same setup is repeated each time: a UI target (web, desktop, native
mobile), an API plane, a model-invocation plane, an OpenAPI contract, streaming
events, local/remote deployment, build pipelines, and the agent runtime that
makes tools, skills, MCP and System One work. The playbook already owns the
cross-cutting packages and the assembly skill, but it has no deterministic way
to materialize the infrastructure a new project starts from. ADR-0025 forbids
becoming a code generator, so the boundary needs to be stated explicitly
before the scaffold is built.

## Decision

1. **Three planes and one contract.** An application is a thin UI plane, an
   API plane that owns authentication, agent state and orchestration, and a
   model-invocation plane. The UI talks to the API over OpenAPI request/response
   plus a versioned streaming-event schema. The UI never calls model providers
   directly and never carries provider keys.
2. **AgentCore lives in the API plane.** `cliver-core` `AgentCore` (tools,
   skills, MCP, System One/Laya, capabilities, pipelines) is the canonical
   agent runtime. It runs in Python, locally or remotely. A Rust API is a
   BFF/gateway that validates identity, shapes responses and proxies streams;
   it delegates agent runs to the Python AgentCore service and does not
   reimplement skills, MCP or System One. The API plane's internal topology —
   one coordinator plus N business-point sub-agents, each with a
   self-enhancing pipeline seam — is ADR-0027.
3. **Desktop local mode is sidecars.** A Tauri 2 desktop shell starts the API
   and model planes as loopback sidecars with an ephemeral port and a
   per-session token. The UI still calls HTTP. Web and mobile use the remote
   API; mobile never starts a local service.
4. **The TypeScript framework is for the UI, not the agent.** Web and desktop
   use Vercel AI SDK for streaming chat state, message parts and tool-call
   rendering, with a custom transport over the project's event contract. It is
   not a second agent runtime. A TypeScript agent runtime (for example Mastra)
   is a separate, ADR-level decision and is not part of this architecture.
5. **Native mobile, not React Native.** iOS is SwiftUI and Android is
   Kotlin/Compose. Mobile UX is the product's priority, so the scaffold accepts
   two native codebases; it does not default to RN/Expo. Start with one
   platform and add the second after it is validated.
6. **The scaffold is manifest-driven and infrastructure-only.** A project
   manifest selects a profile and modules; the scaffolder resolves the module
   set and materializes the infrastructure skeleton. It is deterministic,
   idempotent, refuses to overwrite a non-empty target, and generates no domain
   entities, workflows, prompts or copy. Generated files are project-owned
   immediately; templates are not a runtime dependency. Opt-in reference
   slices (the products CRUD example on web and native mobile) are explicitly
   labelled examples, selected by `scaffold.reference_slices`, and may be
   deleted or replaced; they do not make the scaffolder a domain generator.
7. **Contracts are the first artifact.** OpenAPI fragments from the selected
   modules compose into the project's `contracts/openapi.yaml`; the streaming
   event union lives in `contracts/events.json`; clients for TypeScript, Swift,
   Kotlin, Python and Rust are generated. The API is contract-tested, and CI
   fails when generated clients drift from the spec.
8. **Profiles stay small; features are flags.** The scaffold ships five
   profiles: `ai-web`, `ai-desktop`, `ai-mobile`, `ai-full` and `ai-rust-bff`.
   Auth, settings, agent, RAG, MCP, files, billing and model capabilities are
   selectors, not new profiles. Native mobile features are selectors too:
   authentication/registration, profile, the reference product CRUD slice, and
   phone/pad responsive layouts. Every profile is tested; combinations that are
   not tested are not promised.
9. **A script and a skill, not a prompt-to-app generator.** The manifest
   planner/apply script is the deterministic implementation. The assembly skill
   helps a coding agent choose modules, write the manifest, run the planner,
   prove the first vertical slice and pass the gates. The script records module
   choices, the playbook revision and template hashes in `.scaffold/state.json`.
   It does not auto-upgrade a project; upgrades are documented diffs.
10. **Chat-first UI with replaceable components.** The generated app's primary
    home is a simple conversation surface. Intent recognition and routing live
    in the API/AgentCore plane; the UI renders a typed route event and
    navigates. Every visual primitive sits behind a per-platform component
    seam (web `src/ui`, iOS `AppComponents`, Android `AppComponents`), so a
    consumer can replace the chat bubble, composer, tool-call card, auth form,
    list or editor without changing the feature flow. Reference components are
    deliberately simple examples, not the product's final design.

## Amendment to ADR-0025

ADR-0025 rejects "generating an application from a prompt" and "replacing
coding agents". It does not reject a deterministic scaffolder that materializes
an explicit infrastructure manifest. The distinction is:

- **In scope:** creating the workspace layout, contracts, build/CI files,
  sidecar configuration and empty feature modules selected by a manifest.
- **Still out of scope:** generating domain models, business workflows, prompts,
  copy or page composition; making architecture decisions from a prompt; owning
  project control flow after scaffold time.
- **Exit path:** generated files are project-owned, templates are removable,
  and no project imports the scaffold at runtime.

## Consequences

- A new project starts with a contract, typed clients, a runnable API/model/UI
  skeleton and CI, instead of re-deriving the same architecture.
- The playbook gains a template tree, a module catalog, a manifest schema and a
  planner; each is versioned and tested with the packages.
- Template drift is a real risk; golden plans, contract tests and the
  generated-client drift check are part of the release gates.
- The mobile decision costs two native codebases; the scaffold compensates with
  generated clients, shared design tokens and shared contract tests, and starts
  with one platform. Each native fragment ships auth, profile, the reference
  product CRUD slice and adaptive phone/pad layouts so the first product screen
  is real code, not a placeholder.
- Reference slices are opt-in and deletable; the project replaces them with its
  own domain. The scaffolder's infrastructure guarantee is unchanged.
- The UI seam adds one small abstraction per platform, but keeps the reference
  screens simple and prevents a consumer from forking feature flows just to
  change a visual component. The chat surface is the default entry; direct
  routes remain for custom navigation.
- The Rust BFF adds a hop and a service; it stays optional and is selected only
  when a concrete edge/performance requirement exists.
- A project can diverge from the template at any time; the scaffold does not
  become an upgrade dependency.

## Alternatives considered

- **Put the scaffold in a separate repository:** rejected for now — it would
  drift from the packages and the skill, and the playbook is already the
  distribution point. Revisit if the template tree outgrows the repository.
- **Use Copier or Cookiecutter as the engine:** rejected for the initial
  implementation — the module matrix needs composition and explicit conflict
  resolution; a small fragment composer with a manifest schema is easier to
  test. Generated files are project-owned, so update machinery is not a goal.
- **Generate the application from a prompt:** rejected by ADR-0025. The
  manifest is explicit and reviewable; the coding agent still writes domain
  code.
- **Make the scaffold a framework with runtime hooks:** rejected. Templates
  are copied, not imported; the playbook packages remain the runtime seams.
- **React Native/Expo for mobile:** rejected because mobile experience is the
  priority and the product is willing to maintain native shells. RN remains a
  documented fallback only if the native cost becomes the bottleneck.
- **A TypeScript agent runtime in the UI:** rejected. It would fork skill/MCP
  semantics, duplicate AgentCore, and put provider keys in the client.
- **A Rust AgentCore reimplementation:** rejected. The Rust API is a BFF; the
  agent runtime stays in one place.
