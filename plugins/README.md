# Agent plugins

One portable source per plugin, rendered into the three agent platforms the
playbook supports. The source is an open Agent Skill plus a connector
declaration; platform manifests are generated, never hand-maintained.

```
plugins/<name>/
├── plugin.json            # single source of truth (name, version, copy, mcp url)
├── skill/<skill>/SKILL.md # open Agent Skills format, portable as-is
├── skill/<skill>/references/…
└── connector/icon.svg     # optional; used by WorkBuddy
```

Build and validate from the repository root:

```bash
make plugin-check                    # validate every plugin, write nothing
make plugin-package                  # build dist/plugins/*.zip for every plugin
make plugin-package APP=cliver-governed-kb MCP_URL=https://…/mcp
```

`scripts/package_plugin.py` renders:

| Target | Bundle |
|---|---|
| `claude-code` | `.claude-plugin/plugin.json`, `skills/`, `.mcp.json` (install directly or list in a marketplace) |
| `codex` | `.codex-plugin/plugin.json`, `skills/`, `mcp.json` |
| `workbuddy` | `connector-meta.json`, `mcp.json`, `icon.svg`, `skills/` with WorkBuddy's extra frontmatter injected |

The same MCP endpoint is spelled differently per platform (`type: http`,
bare `url`, `type: streamableHttp`); the generator owns that difference. The
source `SKILL.md` stays standard — WorkBuddy-only fields are injected into the
generated copy.

Rules the check enforces: kebab names, semver, en+zh copy, one skill whose
`name` matches its directory, an HTTPS connector URL, no credential-shaped
strings, and WorkBuddy's required frontmatter after the merge.

## Plugins in this repository

- `cliver-governed-kb` — the governed knowledge-base skill and connector
  contract. The skill drives the governance loop through three MCP tools
  (`governed_kb_list_projects`, `governed_kb_project_status`,
  `governed_kb_ask`); the demo server currently exposes `echo` and
  `user_directory`, so the business tools are the next server-side step
  (see the plugin's `references/tools.md`).
