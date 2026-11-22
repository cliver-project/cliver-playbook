# Configure System One

## Use when

The project has a large tool/skill catalogue that dilutes the main model, or a
decision needs a small typed judgement instead of generated text: which tools
or skills fit a request, which intent rule applies, or a yes/no/score question.
System One models return `Choice` / `Score` / `Noul` probabilities, never prose.

Profile: `ai-native` with the `agent` feature (tool/skill filtering) or
`rag_governance` (intent routing).

## Do

### 1. Enable it in the agent manifest

The scaffolded agent fragment already wires `SystemOneSelector` as AgentCore's
`candidate_selector`. Add both switches:

```yaml
model:
  capabilities: [llm, embedding, rerank, system_one]
agent:
  runtime: agentcore
  system_one: true
```

The selector is opt-in and fail-open: it only runs when a catalogue exceeds
`min_tools` / `min_skills`, and any provider error keeps the full catalogue.
Use it for tools/skills, not for the main chat call.

### 2. Configure a provider

Set one provider in the environment or `.env`:

```sh
CLIVER_AGENT_SYSTEM_ONE_PROVIDER=local       # local | bailian | typesafe | http
CLIVER_AGENT_SYSTEM_ONE_MODEL=multilingual
# CLIVER_AGENT_SYSTEM_ONE_API_KEY=...
# CLIVER_AGENT_SYSTEM_ONE_BASE_URL=...
CLIVER_AGENT_SYSTEM_ONE_MIN_TOOLS=20
CLIVER_AGENT_SYSTEM_ONE_TOP_K_TOOLS=10
```

`local` needs the optional extra: `uv sync --extra local-system-one`. `bailian`
also needs `CLIVER_AGENT_SYSTEM_ONE_WORKSPACE_ID`; `http` needs a base URL and
model. Empty provider disables the selector; an invalid provider fails startup.

### 3. Call System One explicitly when needed

The generated agent factory mounts the same `system_one` binding on
`ModelBindings` and on the selector (`build_model_bindings` in
`app/agents/core.py`), so `AgentCore.system_one` works for project code that has
the agent open:

```python
from cliver_core.system_one import Choice

result = await agent.system_one(
    "Order 42 is late; the customer wants a refund.",
    {
        "refund": Choice(
            instructions="Should this request use a refund tool?",
            criteria={
                "refund": "The user explicitly asks for money back.",
                "status": "The user only asks where the order is.",
            },
        )
    },
)
answer = result.answers["refund"]
```

Without an AgentCore run, use the binding directly:
`provider = binding.build_provider()`, then
`await provider.system_one(state=..., questions=..., model=binding.model)`.
Close the binding with `await binding.aclose()` when you own it.

### 4. Optional: route governance intent rules

The governed query facade uses deterministic keyword-regex rules by default.
For a large or ambiguously phrased rule set, build a binding in project code and
put the router on the app state before serving requests:

```python
from cliver_core import ModelBinding
from cliver_playbook.app.rag_governance.rules.system_one import SystemOneIntentRouter

binding = ModelBinding.system_one(
    model="decision-model-preview",
    base_url="https://.../compatible-mode",
    api_key="...",
)
app.state.intent_router = SystemOneIntentRouter(binding=binding, threshold=0.5)
```

A router failure, malformed answer, or empty selection falls back to the
keyword classifier. The router returns every rule above the threshold so
priority/union scope composition still works. Keep the rule set under the
router's `max_rules` (default 32).

## Verify

- `make system-one-smoke` exercises the local selector without the main model.
- The agent runtime settings/endpoint shows the configured provider.
- For tool filtering, a request that needs a specific tool still gets it; an
  unrelated low-fit tool is omitted.
- For governance routing, ask a question whose wording does not contain the
  rule keywords and confirm the intended intent; then break the provider and
  confirm the keyword fallback still answers.
- An empty provider must produce no selector/router; an invalid provider must
  fail startup, not silently fall back.

## Pitfalls

- **Do not use System One for generation.** It returns probabilities; the
  main LLM still writes the answer.
- **Do not rely on it being available.** Every call path must be fail-open;
  the selector and router already are.
- **Do not send huge catalogues.** The close read has a 15-candidate / 16-question
  ceiling; keep thresholds and top-k small.
- **Do not put API keys in project config or git.** Use environment/settings.
- **Do not duplicate the binding.** Pass the same binding to the selector and
  `ModelBindings(system_one=...)` when both are used in one run.
- **A local decision model is heavy.** It is optional (`local-system-one`) and
  cached process-wide; close it on shutdown.

## Source of truth

- `var/playbook/scaffold/fragments/api.agent/files/services/api/app/agents/core.py`
  — `build_system_one_binding`, `build_system_one_selector`,
  `build_model_bindings` and the local provider cache.
- `var/playbook/scaffold/fragments/api.agent/files/services/api/app/agents/runner.py`
  — `candidate_selector=build_system_one_selector(settings)`.
- `var/playbook/scaffold/fragments/api.python/files/services/api/app/settings.py.j2`
  — `agent_system_one_*` fields and validation.
- `var/playbook/packages/backend/cliver-playbook-app-rag-governance/src/cliver_playbook/app/rag_governance/rules/system_one.py`
  — `SystemOneIntentRouter`.
- `var/playbook/packages/backend/cliver-playbook-app-rag-governance/src/cliver_playbook/app/rag_governance/query/facade.py`
  — router hook and keyword fallback.
- Deep dive: `reference/decision-guide.md` section "System One".
