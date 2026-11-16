# Package a capability as an agent plugin

## Use when

- The user wants the project's capability usable from **Claude Code, Codex or
  WorkBuddy** (a "skill + connector" / plugin) rather than only from the web UI.
- The user asks to publish to a platform's marketplace, or to hand a
  colleague a ZIP that installs the skill and its MCP connector together.
- The capability already exists over MCP (see `add-mcp-tool.md`); this recipe
  packages the client side. It does not add business tools.

## Do

1. **Pick the plugin name and the MCP server key.** Names are kebab-case and
   global enough to install beside other plugins; the skills are namespaced
   under the plugin name in Claude Code (`/plugin-name:skill-name`).
2. **Create `plugins/<name>/plugin.json`** — the single source of truth.
   Required fields and shapes are documented in `plugins/README.md`:
   `name`, `source`, `version` (semver), `author`, `display_name{en,zh}`,
   `description{en,zh}`, `examples{en,zh}`, `mcp{server_key, default_url}`,
   `targets` (subset of `claude-code`, `codex`, `workbuddy`).
3. **Write the skill once**, in the open Agent Skills format:
   `plugins/<name>/skill/<skill>/SKILL.md` with `name` matching its directory
   and a `description` that says both what it does and when to use it. Put
   tool contracts in `references/` and the business rules in the body. The
   skill encodes the business logic (which tool, in what order, what a
   refusal means); the connector supplies the tools.
4. **Declare the connector URL as configuration.** Keep
   `mcp.default_url` a placeholder and set the real endpoint at package time
   with `MCP_URL=…`; the same URL must be HTTPS. Never commit a deployment
   host or a credential.
5. **Validate and build**:

   ```bash
   make plugin-check
   make plugin-package APP=<name> MCP_URL=https://<host>/mcp
   ```

6. **Validate each artifact for its platform** before publishing:
   `claude plugin validate dist/plugins/claude-code/<name>`, inspect the
   WorkBuddy ZIP with `connector-meta.json`, `mcp.json`, `icon.svg` and
   `skills/…/SKILL.md` (extra frontmatter injected), and load the Claude
   plugin locally with `--plugin-dir` to confirm the skill appears.

## Verify

- `make plugin-check` passes (names, semver, en+zh copy, HTTPS, no secrets,
  WorkBuddy frontmatter after merge).
- `claude plugin validate` reports `Validation passed` for the Claude bundle.
- The ZIP contains exactly the platform layout from `plugins/README.md`.
- With a reachable MCP endpoint, the agent lists the skill and calls a tool
  through it; with a placeholder endpoint, the failure is a clear connection
  error, not a malformed package.

## Pitfalls

- **One source, three manifests.** Do not edit generated trees in `dist/`;
  edit `plugin.json` / `SKILL.md` and rebuild.
- **Transport spelling differs.** Claude Code uses `"type": "http"`, Codex a
  bare `"url"`, WorkBuddy `"type": "streamableHttp"`. The generator owns this;
  hand-written configs drift.
- **WorkBuddy needs more frontmatter.** `display_name`, `display_name_en`,
  `description_zh`, `description_en`, `version`, `author` are injected from
  `plugin.json`; the source skill stays portable.
- **HTTPS only.** WorkBuddy rejects plain HTTP; the check fails the build.
- **No secrets, ever.** The build scans for credential-shaped strings; a real
  scan belongs in CI as well.
- **The skill is not the server.** Packaging a skill whose tools the server
  does not expose ships a broken connector — add the tools first
  (`add-mcp-tool.md`) and test with a real MCP client.

## Source of truth

- `scripts/package_plugin.py` — rendering, validation and ZIP layout.
- `plugins/README.md` — the `plugin.json` contract and per-platform bundles.
- `plugins/cliver-governed-kb/` — a complete reference plugin (skill,
  references, connector icon, three targets).
