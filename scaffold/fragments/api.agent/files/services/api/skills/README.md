# Agent Skills

Drop `SKILL.md` directories here to make them available to sub-agent runs.
`CLIVER_AGENT_SKILLS_DIR` (default `skills`, relative to `services/api`) is the
skills root. Discovery is scoped per agent:

```text
skills/
  shared/                 # visible to every agent
    invoice-policy/
      SKILL.md
  products/               # only the `products` agent
    price-rules/
      SKILL.md
  general/                # only the `general` agent
    help-style/
      SKILL.md
```

A skill placed directly under `skills/` is also discovered (the previous
layout). Later sources override earlier ones by skill name, so the precedence
is root < `shared/` < `<agent-name>/`.

The scaffold does not ship a skill: skills are project-owned content. A
sub-agent run with no configured model never loads them; when a model is
configured, AgentCore discovers them and the model decides when to load one.
