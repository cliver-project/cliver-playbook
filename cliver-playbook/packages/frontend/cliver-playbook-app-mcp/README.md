# cliver-playbook-app-mcp (frontend)

The MCP surface of an app built on cliver-playbook: an in-browser tool
playground (the exact wire protocol an external agent speaks) and the view of
what agents have been calling.

Source-only package, like the two it depends on: `exports` point straight at
TypeScript sources, so the consuming app's Vite build transpiles them — no build
step, no `dist`. It is `private` (installed from the workspace or copied into
the project, never published) and `react`/`react-dom` are peer dependencies (the
app owns the single React instance).

## Layout

| Path | Contents |
| --- | --- |
| `src/index.ts` | The public barrel — routes, nav entries, translations, the API wrappers. |
| `src/routes.tsx` | `mcpRoutes: RouteObject[]` — the pages, permission-gated. |
| `src/nav.ts` | `mcpNavItems` — the header entries this package adds. |
| `src/api/mcp.ts` | Every MCP call: `/api/v1/mcp/*` through the shared client, plus raw JSON-RPC/Sse to the endpoint. |
| `src/pages/MCPPlaygroundPage.tsx` | Tool browser and caller, with the raw response next to the rendered one. |
| `src/pages/admin/MCPAgentsPage.tsx` | Recent tool calls grouped by agent, as recorded in the audit log. |
| `src/components/mcp/` | `AgentBadge`, `CopyButton` — presentation shared by both pages. |
| `src/locales/` | `en.json` / `zh.json` — the keys this package owns, plus `mcpTranslations`. |
| `dev/` | A composed app (basic + user + mcp) that consumes all three by name; the reference wiring. |

## Using it from an app

```tsx
// app/src/main.tsx
import { createI18n } from "cliver-playbook-app-basic";
import { installAuthClient, userTranslations } from "cliver-playbook-app-user";
import { mcpTranslations } from "cliver-playbook-app-mcp";
import "./index.css"; // the app's Tailwind entry — see below

installAuthClient();
createI18n(userTranslations, mcpTranslations);
```

```tsx
// app/src/App.tsx — the app owns the providers and the route table
const routes: RouteObject[] = [
  {
    element: <AuthAppLayout extraNavItems={mcpNavItems} />,
    children: [...basicRoutes, ...userRoutes, ...mcpRoutes],
  },
  ...userStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];
```

Adding this package never means editing a component: `mcpRoutes` and
`mcpNavItems` come from the package, the layout filters the entries against the
viewer's permissions, and each page gates itself with `RequirePerm`. Import
convention, including the extension on deep paths, is the basic package's — see
its README.

### The dev proxy

The MCP endpoint is not under `/api`: the server owns its path shape. The app's
Vite config therefore forwards it as well, naming the backend once:

```ts
// app/vite.config.ts
import { DEV_BACKEND, baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";

export default defineConfig(
  baseConfig({ proxy: { "/mcp": { target: DEV_BACKEND, changeOrigin: true } } }),
);
```

Keep that path in sync with the backend's `mcp.mount_path`. A split deployment
sets `VITE_API_BASE_URL` instead — but note that the playground then calls the
MCP endpoint cross-origin, so the backend's allowed origins have to cover it.

### The app's stylesheet

The app owns its Tailwind entry: it imports the basic package's stylesheet and
names the source root of every other package it uses. The paths must be the
packages' **real** directories — the scanner does not follow symlinks, so
pointing at `node_modules/…` under a linked install is silently ignored and the
utilities used only in that package go missing from the built stylesheet.

```css
/* app/src/index.css */
@import "cliver-playbook-app-basic/styles/index.css";
@source "../cliver-playbook-app-user/src";
@source "../cliver-playbook-app-mcp/src";
```

## Development

From the workspace root:

```sh
pnpm install
pnpm --filter cliver-playbook-dev-mcp dev          # the composed shell, proxying /api and /mcp
pnpm --filter cliver-playbook-app-mcp typecheck
pnpm --filter cliver-playbook-app-mcp lint
```

`dev/` is a throwaway app: it exists so the package can be type-checked, linted
and built as a real consumer would, and so a UI change can be looked at without
spinning up a project. It is also the reference for the full composition — three
packages, one route table, one Tailwind entry.

## Notes

- The playground is a real MCP client, deliberately: it POSTs JSON-RPC with the
  spec-mandated `Accept: application/json, text/event-stream` header, reads SSE
  frames when the server answers with them, and authenticates with the signed-in
  user's own session token. That is why `/api/v1/mcp/*` (ordinary Web API) and
  the endpoint itself (raw transport) live in one module but not one client.
- It identifies itself as the agent type `web-playground`, which has to be in
  the backend's `mcp.agent_type_whitelist` (it is, by default) or the call is
  attributed to `unknown` in the audit log.
- `MCPAgentsPage` reads the same audit rows the backend writes for every tool
  call, so it needs no MCP session of its own — just the `mcp:agents:read`
  permission.
- Locale keys are split by owner: this package ships the `mcp` tree and its
  `nav.mcp*` entries; `auth`/`admin`/`profile` stay in the user package and
  `app`/`common`/`nav.home`/`nav.items` in the basic package. The bundles are
  deep-merged, which is what lets three packages contribute to one `nav` tree.
