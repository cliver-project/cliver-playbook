# AI-native project scaffold

This directory holds the module catalog, manifest schema and fragment templates
for starting a new AI-native project from cliver-playbook. It is infrastructure
only: the scaffold creates the workspace, contracts, build files, UI/API/model
skeletons and reference slices, then the project (and its coding agent) writes
the domain.

The decision record is [ADR-0026](../adr/0026-ai-native-project-scaffold.md).
Maintainer progress and the layered task plan live under
`docs/superpowers/tasks/` (local-only, not shipped).

## Status

Phase 2 is in progress:

- `ai-web` applies a coherent web + Python API + model-service skeleton, with
  contracts, Makefile, GitHub/Gitea CI, Docker assets and a reference product
  CRUD slice. The web app installs, typechecks, lints and builds against the
  pinned tag.
- The Python API skeleton is a multi-agent collaboration platform: a
  coordinator, a sub-agent registry, example products/profile/general agents,
  a run store and a working self-enhancement loop. With a configured model the
  coordinator produces an ordered multi-step AgentCore plan (each later step
  sees earlier results) and each step runs one sub-agent's Re-Act tool loop;
  without one it uses deterministic single-step routing and the direct
  business method. Sub-agents scope their own tools, skills and MCP servers,
  and every runner event carries the executing agent. An optional System One
  selector (local laya, Bailian, TypeSafe or HTTP) narrows large tool/skill
  catalogues as AgentCore's `candidate_selector`; it is fail-open and has a
  `make system-one-smoke` live check. Runs are durable: events land in
  `agent_run_events`, one worker executes each run while streams replay and
  tail it, SSE frames carry `id: <sequence>` for `Last-Event-ID` resume, quiet
  periods get keepalives,
  and vanished workers are marked orphaned instead of retried. Tool, skill,
  MCP and permission seams are opt-in. Each result is also observed into a
  redacted, source-checked experience, scored against a 0.6 launch bar and,
  after sustained low scores, turned into a pending prompt proposal. With a
  configured model, the proposal is distilled from recent redacted outcomes
  and feedback through AgentCore structured output; provider/validation
  failures fall back to the deterministic proposal. When
  golden cases exist, approval also runs an offline baseline-vs-candidate
  gate with safe tools only and fails closed without a model; a reviewer
  (`agent:improve` or admin) approves or rejects it, and approved prompt
  guidance is loaded into the next AgentCore system prompt. Feedback,
  proposals and review decisions are audited, and the web chat exposes
  Helpful / Not helpful after a run.
- The Android and iOS fragments generate module-per-feature apps with auth,
  profile, product CRUD and adaptive phone/tablet layouts. The iOS app builds
  with XcodeGen/Xcode unsigned; the Android app builds and unit-tests with
  JDK 17, API 35, Build-Tools 35.0.0 and Gradle 8.10.2.
- The desktop Tauri shell is minimal; local sidecars, signing and the updater
  are the next desktop phase.
- The `ai-rust-bff` profile is planned but not implemented.
- UI direction: a simple chat-first surface (intent routing in the API plane)
  with every visual component behind a replaceable per-platform seam. The web
  reference is implemented: `/` streams agent events, routes selected business
  agents to feature actions, keeps all visuals in `apps/web/src/ui` with a
  `seam-check` gate, and has a Playwright chat E2E with a mocked API. iOS
  exposes `AppComponents` and a chat-first Assistant
  tab; Android has the component seam, chat-first Assistant screen and a
  passing Gradle build.

Every generated file is project-owned. The scaffold does not upgrade a project
and is not a runtime dependency.

## Usage

```sh
# Print the resolved module set, outputs, make targets and CI workflows.
uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
  --plan scaffold/examples/ai-web.yaml

# Apply to a new directory. The target must be absent or empty.
uv run --with pyyaml --with jsonschema --with jinja2 \
  python scripts/scaffold_project.py --apply scaffold/examples/ai-web.yaml \
  --target ../example-ai-web

# List every module, profile and selector as JSON.
uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
  --list-modules

# Validate the catalog, schema and every example manifest.
uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
  --validate-catalog

# Built-in tests, including real ai-web apply and mobile feature wiring.
uv run --with pyyaml --with jsonschema --with jinja2 \
  python scripts/scaffold_project.py --self-test
```

`make scaffold-check` runs the self-test and catalog validation.
`make scaffold-plan MANIFEST=scaffold/examples/ai-web.yaml` prints a plan.

## Manifest in one screen

```yaml
project: example-ai-app
playbook:
  source: <playbook repository>
  revision: "X.Y.Z"
scaffold:
  template: ai-native
  profile: ai-web          # ai-web | ai-desktop | ai-mobile | ai-full | ai-rust-bff
  reference_slices: [products]  # optional, clearly marked examples
ui:
  web: true
  desktop: none            # none | tauri2
  mobile:
    ios: none              # none | swiftui
    android: none          # none | kotlin
    features: [auth, profile, crud]  # mobile only; default is all three
    layouts: [phone, pad]            # mobile only; default is both
api:
  runtime: python          # python | rust
  deployment: remote       # remote | local | both
  features: [auth, settings, agent, rag, mcp]
model:
  runtime: python
  deployment: remote       # remote | local | both
  capabilities: [llm, embedding, rerank, asr, image, system_one]
agent:
  runtime: agentcore       # agentcore | none
  skills: true
  mcp: true
  system_one: true
contracts:
  openapi: contracts/openapi.yaml
  events: contracts/events.json
ci:
  provider: github         # github | gitea | both
release:
  desktop: false
  mobile: false
```

The profile fixes the deployment shape; the fields must match it. Features,
model capabilities, mobile features/layouts and reference slices are selectors
layered on top. The planner rejects contradictory shapes, a mobile target with
a local-only API/model, a local deployment without a desktop shell, an agent
feature without AgentCore, a release target without its UI, and similar invalid
combinations.

## Profiles

| Profile | Shape |
|---|---|
| `ai-web` | Browser UI, remote Python API, remote model service. |
| `ai-desktop` | Web UI in a Tauri 2 shell, local API/model sidecars, remote fallback. |
| `ai-mobile` | One native mobile client, remote API and model. |
| `ai-full` | Web, desktop and at least one native mobile target; local and remote. |
| `ai-rust-bff` | Web UI, Rust BFF edge, internal Python AgentCore service, remote model. |

`ai-full` with both mobile targets emits a warning: that is two UI codebases.
Start with one platform.

## Reference slices

`reference_slices: [products]` adds the product list/detail/edit/delete example
to the web and native clients, plus `api.products`. It is an example, not a
domain base: the project owns it and should replace it. The planner warns that
reference slices are examples. A Rust API cannot use the Python reference slice.

## Rules

- No deployment-specific hosts, credentials or provider endpoints in the
  catalog, schema, examples or fragments.
- No domain logic is generated outside the clearly marked reference slices.
- Generated files belong to the project; there is no automatic template update.
- The UI never calls a model provider directly; the API plane owns AgentCore.
- The UI is chat-first and component-replaceable. Feature pages import only
  the platform UI seam, never a deep reference visual path. Intent recognition
  belongs to the API plane.
- Rust is a BFF, not a second agent runtime.
- Native mobile is the default; React Native/Expo is not part of this scaffold.
