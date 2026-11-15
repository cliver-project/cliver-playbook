# Start an AI-native project from the scaffold

## Use when

Starting a brand-new AI-native application rather than composing the package
library into an existing service. The scaffold materializes a project-owned
skeleton: web, Tauri desktop and native mobile clients, a Python multi-agent
API plane, contracts, migrations, CI and packaging targets.

Profile: `ai-native` scaffold (`ai-web`, `ai-desktop`, `ai-mobile`, `ai-full`).

This is a separate on-ramp from the package profiles. The generated project
does not depend on the checkout after generation.

## Do

### 1. Fetch the pinned playbook checkout

Use the release the project should pin; the checkout is reference material.

```sh
git clone <playbook-repository> var/playbook
git -C var/playbook checkout <tag-or-commit>
```

### 2. Turn the brief into a manifest

**You are the parser for this step.** The scaffold script accepts YAML only;
it does not understand prose. The user speaks naturally, and you infer, ask
blocking questions, write the YAML, plan, confirm and apply. Do not ask the
user to write YAML or to run the generation commands; execute them yourself
unless the environment forbids it.

Read the brief and infer the smallest manifest. Map it as follows, then show
the manifest and plan before applying:

| Brief signal | Manifest fields |
|---|---|
| Web UI | `ui.web: true` |
| Installable desktop app | `ui.desktop: tauri2`, `release.desktop: true` |
| iPhone/iPad or Android | `ui.mobile.ios: swiftui` / `ui.mobile.android: kotlin`, layouts `[phone, pad]` |
| Accounts, roles, profile | `api.features` includes `auth`, `settings`; mobile features include `auth`, `profile` |
| AI assistant/tools/MCP | `api.features` includes `agent`, optionally `mcp`; `agent.runtime: agentcore` |
| Knowledge base | `api.features` includes `rag` |
| Local/offline models | `api.deployment: local`, `model.deployment: local`, desktop |
| Reference CRUD | `scaffold.reference_slices: [products]` |
| All clients | `ai-full` profile |
| One native client | `ai-mobile` with the requested platform |

Ask only about choices that change modules: platforms, accounts, RAG/MCP,
local vs remote models, and release targets. Ask at most three questions per
round. If the user says "you decide", use the table's default, record the
assumption under `decisions` in the manifest, and continue.

Example briefs and inferred starts:

- "Browser-only AI assistant with login and a product list" → `ai-web`,
  `ui.web: true`, `api.features` includes `auth`, `settings`, `agent`, remote
  models, `scaffold.reference_slices: [products]`.
- "Web, macOS/Windows installer, iPhone and Android from day one" → `ai-full`,
  remote API/models, mobile features `[auth, profile, crud]`, release desktop
  and mobile.
- "Only an iPhone/iPad native client" → `ai-mobile` with
  `ui.mobile.ios: swiftui`; do not enable web or Android.
- "Desktop installer that works offline with local models" → `ai-desktop`,
  local API and model deployment, desktop release.
- "Add a knowledge base and MCP tools to the assistant" → keep the chosen
  profile, add `rag`/`mcp` to `api.features`, enable `agent.mcp` as needed.

Start from the nearest example:

- `scaffold/examples/ai-web.yaml` — web + API, no mobile/desktop.
- `scaffold/examples/ai-desktop.yaml` — web + Tauri desktop + local sidecars.
- `scaffold/examples/ai-mobile.yaml` — one native mobile target + API.
- `scaffold/examples/ai-full.yaml` — web + desktop + iOS + Android + API.
- `scaffold/examples/ai-rust-bff.yaml` — plan-only until the Rust fragments
  exist; apply rejects it explicitly.

`ai-full` is the acceptance path for "all clients on day one". Copy it beside
the project, set `project`, and adjust `ui`, `api.features`, `reference_slices`
and `release` deliberately.

### 3. Plan, then apply into an empty directory

Run these commands yourself and report their real output. Show the plan and
warnings before asking for confirmation; the user should not have to invoke
the script.

```sh
python3 var/playbook/scripts/scaffold_project.py \
  --plan scaffold/examples/ai-full.yaml

python3 var/playbook/scripts/scaffold_project.py \
  --apply scaffold/examples/ai-full.yaml \
  --target ../example-ai-full
```

The target must not exist or must be empty. The scaffolder writes
`project-manifest.yaml`, `SCAFFOLD.md` and `.scaffold/state.json`, and never
renders Jinja into the output.

### 4. Initialize and start

```sh
cd ../example-ai-full
make init          # Python API, model service and web dependencies
make contracts     # align generated clients/native manifests with this contract
make db-init       # PostgreSQL + every migration chain
make dev           # API, model service and web UI
# Optional: run execution separately with make dev-worker after disabling the
# API's in-process consumer (CLIVER_AGENT_RUN_WORKER_ENABLED=false).
```

The API owns AgentCore, the agent runtime, authentication and model routing.
The model service is internal. With no model configured the coordinator uses
deterministic routing and the reference business methods; set
`CLIVER_AGENT_LLM_MODEL` plus a base URL/provider to enable AgentCore planning
and the sub-agent tool loop. The UI never calls a provider.

### 5. Run the project gates

```sh
make check         # API/model tests, web checks, contract check, mobile tests
make contract-test # Schemathesis against a live scratch-DB API
make web-e2e       # mocked chat and learning-dashboard flows
make web-e2e-real E2E_USERNAME=<admin> E2E_PASSWORD=<password>  # live API
```

Expected baseline at the time of writing: 128 API tests in `ai-full`, the
model-service health test, the web typecheck/lint/seam/build and 9 mocked
Playwright checks (chat, sessions, runtime, learning and axe), iOS Core tests
and Android unit plus adaptive tests. Counts evolve with the playbook; use the
suite's current count. `make contracts-check` verifies generated clients;
`make contract-test` runs 1,000+ generated cases with response-schema
conformance and no 5xx; `make web-e2e-real` signs in, chats, submits feedback
and loads the learning dashboard.
`make test-api` uses a scratch PostgreSQL database; set
`CLIVER_TEST_DATABASE_URL` when the default local DSN does not apply.

### 6. Package local artifacts

```sh
make build         # API wheel, web bundle and enabled mobile builds
make package       # host desktop bundle plus unsigned mobile artifacts
```

Outputs:

- `services/api/dist/` — API wheel.
- `apps/web/dist/` — static web bundle.
- `apps/ios/build/Build/Products/Debug-iphonesimulator/` — simulator `.app`.
- `apps/android/app/build/outputs/apk/debug/app-debug.apk` — debug APK.
- `apps/desktop/src-tauri/target/release/bundle/` — host desktop bundle.

The mobile artifacts are unsigned local builds. Use Xcode/Android Studio with
the project's signing identity for device or store distribution. The Android
Gradle wrapper is checked in; no machine-wide Gradle install is required.

### 7. Replace the reference slice

`products` is a reference vertical slice, not domain code. Replace it with the
project's own entities and sub-agents through the registry/toolkit seams, and
keep the self-enhancement pipeline: redacted experience storage, feedback,
the launch-bar evaluation, golden-set gate, reviewer approval and prompt
overlay.

## Verify

```sh
make test-api
make web-check
make contract-test
make test-ios
make test-android
make package
```

A fresh `ai-full` project must produce the current API suite passing, a
passing web build/E2E, and the five artifact locations above. Re-running the
scaffolder into the same target must fail instead of overwriting project-owned
code. `make contracts-check` must pass after `make contracts`.

## Pitfalls

- **Do not scaffold into a non-empty directory.** Apply refuses it; create the
  project in a new folder instead.
- **One project, one manifest.** The generated project owns its files. To add
  or remove a feature later, change the project's own code or deliberately
  re-scaffold a new variant; the scaffolder is not an upgrader.
- **Docker port conflict.** The default PostgreSQL port is 5432. If it is
  occupied, set `DB_PORT` for compose and point `CLIVER_DATABASE_URL` at the
  same port for migrations and the API.
- **Xcode selection.** The Makefile falls back to the standard Xcode install
  when `xcode-select` points at Command Line Tools. Set `XCODE_DEVELOPER_DIR`
  if Xcode lives elsewhere.
- **Unsigned is not distributable.** `make package` is for local inspection and
  smoke tests; store builds need signing and notarization credentials.
- **No secrets in the project.** Keep `.env`, keys and build output out of git.
- **Use the scaffold, not package assembly.** For an AI-native app call
  `scaffold_project.py`; `assemble_project.py` is for non-AI-native package
  composition.
- **Do not hand-write wire types.** Run `make contracts` after changing the
  manifest or a contract fragment; TypeScript, Python, Swift and Kotlin clients
  are generated and gated.
- **Do not expect hosted staging from a local build.** Real-model local smoke
  is available; hosted staging needs a deployed target and secrets, not just a
  model API key.

## Source of truth

- `scaffold/README.md` — catalog, profiles, apply behavior and current limits.
- `scaffold/examples/ai-full.yaml` — the full client/API manifest.
- `scripts/scaffold_project.py` — validation, plan, apply and self-test.
- `adr/0026-ai-native-project-scaffold.md` — scaffold boundaries.
- `adr/0027-multi-agent-api-plane.md` — coordinator, sub-agents and
  self-enhancement contract.
