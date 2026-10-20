# Frontend composition

The frontend is a Vite + React 19 + Tailwind v4 application at the project
root. The playbook packages are installed as TypeScript sources from the
release tag; the app's build transpiles them. There is no npm registry
package, no `dist` to import, and no build step on the library side.

## Install model

Pin the tag in three places: the direct dependency URLs, the pnpm `overrides`,
and the backend pins. All of them carry the same `X.Y.Z`.

```json
{
  "name": "example-app",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b",
    "lint": "oxlint",
    "preview": "vite preview"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.90.0",
    "cliver-playbook-app-basic": "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-basic",
    "cliver-playbook-app-user": "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-user",
    "cliver-playbook-app-rag": "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-rag",
    "cliver-playbook-app-mcp": "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-mcp",
    "react": "^19.2.0",
    "react-dom": "^19.2.0",
    "react-router-dom": "^7.18.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.3.0",
    "@types/node": "^24.0.0",
    "@types/react": "^19.2.0",
    "@types/react-dom": "^19.2.0",
    "@vitejs/plugin-react": "^6.1.0",
    "oxlint": "^1.79.0",
    "tailwindcss": "^4.3.0",
    "typescript": "~6.0.2",
    "vite": "^8.2.0"
  }
}
```

Keep only the playbook packages for the chosen profile:
`minimal` → basic; `web` → basic + user; `rag` → + rag; `mcp` → + mcp.
`react` and `react-dom` are peer dependencies of the packages, so the app owns
the single React instance and must declare them.

`pnpm-workspace.yaml`:

```yaml
packages: []

# Git dependencies are "exotic"; pnpm blocks them in subdependencies by
# default. The overrides are required even for packages this project does not
# import directly, because e.g. the user package depends on
# cliver-playbook-app-basic at "0.1.0" — a version that exists only as a git
# tag, not in a registry.
blockExoticSubdeps: false
overrides:
  cliver-playbook-app-basic: "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-basic"
  cliver-playbook-app-user: "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-user"
  cliver-playbook-app-rag: "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-rag"
  cliver-playbook-app-mcp: "github:cliver-project/cliver-playbook#0.1.0&path:/packages/frontend/cliver-playbook-app-mcp"
```

`overrides` must list all four packages even when the project selects two.
List every selected package in `dependencies`; the unselected ones in
`overrides` only prevent a registry lookup from a sibling's version pin.

`.npmrc`:

```ini
# pnpm's default isolated linker puts each package behind a symlink into
# .pnpm/. Tailwind's @source scanner needs a real directory; hoisted installs
# the packages as real directories under node_modules.
node-linker=hoisted
```

If the repository is private, configure git credentials for pnpm before
installing. Commit `pnpm-lock.yaml`; install with
`pnpm install --frozen-lockfile` in CI and production builds.

## Shell files

Copy these from the matching playbook dev shell
(`var/playbook/packages/frontend/cliver-playbook-app-<profile>/dev/`); the
`mcp` shell is the full reference.

| File | Origin | Project change |
|---|---|---|
| `index.html` | `cliver-playbook-app-basic/tooling/index.html` | `<title>`, favicon |
| `vite.config.ts` | dev shell | add `/mcp` proxy only for mcp |
| `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json` | dev shell | none |
| `.oxlintrc.json` | dev shell | none |
| `package.json` | dev shell adapted | real name, git dependency URLs |
| `public/favicon.svg` | dev shell | replace with the product's mark |

`index.html` contains an inline no-flash script that sets `data-theme` before
first paint. Keep it inline (it cannot be imported) and keep its storage key
`cliver-theme` in sync with `ThemeProvider`.

`tsconfig.app.json` extends the package's base and includes `src`; do not
copy the base into the project:

```json
{
  "extends": "cliver-playbook-app-basic/tooling/tsconfig.base.json",
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "types": ["vite/client"]
  },
  "include": ["src"]
}
```

`vite.config.ts` names the backend once through the shared base:

```ts
import { defineConfig } from "vite";

import { DEV_BACKEND, baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";

export default defineConfig(
  // The MCP endpoint lives outside /api and the playground is a real MCP
  // client, so the dev server must forward it too. A minimal/web/rag app
  // omits this argument.
  baseConfig({ proxy: { "/mcp": { target: DEV_BACKEND, changeOrigin: true } } }),
);
```

Keep `/mcp` in sync with the backend's `mcp.mount_path`. Same-origin is the
default, so no CORS setup is needed in development.

## Entry point

`src/main.tsx` for the `mcp` profile. Every line before `createRoot` is
order-dependent.

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createI18n } from "cliver-playbook-app-basic";
import "./index.css";
import { mcpTranslations } from "cliver-playbook-app-mcp";
import { ragTranslations } from "cliver-playbook-app-rag";
import { installAuthClient, userTranslations } from "cliver-playbook-app-user";

import App from "./App";
import { projectTranslations } from "./i18n";

// Axios interceptors are global: install before the first request.
// i18next must be initialised before the first component renders.
installAuthClient();
createI18n(userTranslations, ragTranslations, mcpTranslations, projectTranslations);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Per profile:

| Profile | `installAuthClient` | Bundles |
|---|---|---|
| `minimal` | no | `projectTranslations` |
| `web` | yes | `userTranslations`, `projectTranslations` |
| `rag` | yes | `userTranslations`, `ragTranslations`, `projectTranslations` |
| `mcp` | yes | all four |

`createI18n` deep-merges per language, so the project's bundle can override
`app.title` and add its own keys without copying the packages' files. Pass the
project bundle last; later bundles win on conflicts.

## Route table

`src/App.tsx` for the `mcp` profile:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, useRoutes, type RouteObject } from "react-router-dom";

import { ThemeProvider, Toaster, basicRoutes, queryClient } from "cliver-playbook-app-basic";
import { mcpNavItems, mcpRoutes } from "cliver-playbook-app-mcp";
import { ragNavItems, ragRoutes, ragStandaloneRoutes } from "cliver-playbook-app-rag";
import {
  AuthAppLayout,
  AuthProvider,
  userRoutes,
  userStandaloneRoutes,
} from "cliver-playbook-app-user";

import { projectNavItems, projectRoutes } from "./routes";

const routes: RouteObject[] = [
  {
    element: (
      <AuthAppLayout extraNavItems={[...ragNavItems, ...mcpNavItems, ...projectNavItems]} />
    ),
    children: [...basicRoutes, ...userRoutes, ...ragRoutes, ...mcpRoutes, ...projectRoutes],
  },
  ...userStandaloneRoutes,
  ...ragStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];

function AppRoutes() {
  return useRoutes(routes);
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
            <Toaster />
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
```

Per profile:

| Profile | Layout | Providers | Extra children |
|---|---|---|---|
| `minimal` | `AppLayout` | query, theme, router | `basicRoutes` |
| `web` | `AuthAppLayout` | + `AuthProvider` | `+ userRoutes`, `...userStandaloneRoutes` |
| `rag` | `AuthAppLayout` + `ragNavItems` | + `AuthProvider` | `+ ragRoutes`, `...ragStandaloneRoutes` |
| `mcp` | `AuthAppLayout` + `mcpNavItems` | + `AuthProvider` | `+ mcpRoutes` |

Provider order is load-bearing: query cache → theme → router → auth. Do not
invent a second router, a second i18next instance, or a second query client.

## Project routes and navigation

The route table is data, so the project adds pages without editing a package.

```tsx
// src/routes.tsx
import type { RouteObject } from "react-router-dom";

import { RequirePerm, type AuthedNavItem } from "cliver-playbook-app-user";

import OrdersPage from "./pages/OrdersPage";

export const projectRoutes: RouteObject[] = [
  // Relative: these are children of the layout route.
  {
    path: "orders",
    element: (
      <RequirePerm code="orders:read">
        <OrdersPage />
      </RequirePerm>
    ),
  },
];

// Absolute: the header links to the mounted path. `perm` hides the entry
// from viewers without the code; null means always visible.
export const projectNavItems: AuthedNavItem[] = [
  { to: "/orders", labelKey: "nav.orders", perm: "orders:read" },
];
```

- Route paths inside the layout's `children` are relative (`"orders"`).
- `NavItem.to` is absolute (`"/orders"`), because `NavLink` matches against
  the browser location.
- `extraNavItems` takes `AuthedNavItem` (a `NavItem` plus `perm`), which is
  why the project's list is typed that way. For the `minimal` profile there is
  no user package: use `AppLayout` with
  `navItems={[...basicNavItems, ...projectNavItems]}`, where
  `projectNavItems: NavItem[]` has no `perm`.
- `RequirePerm` is a UI affordance, not enforcement: the server checks the
  same code on every request.
- Add `nav.orders` and the page's keys to `src/locales/en.json` and
  `src/locales/zh.json`. Missing keys render as the key itself; the admin
  runtime-settings page is the one place with a server-side English fallback.

```ts
// src/i18n.ts
import type { TranslationBundle } from "cliver-playbook-app-basic/i18n/createI18n.ts";

import en from "./locales/en.json";
import zh from "./locales/zh.json";

export const projectTranslations: TranslationBundle = { en, zh };
```

```json
{
  "nav": { "orders": "Orders" },
  "orders": {
    "title": "Orders",
    "empty": "No orders yet"
  }
}
```

## The Tailwind entry

The app owns exactly one file that imports Tailwind: `src/index.css`. It pulls
in the basic package's stylesheet (Tailwind itself, the tokens, and the basic
package's own `@source`) and names every other package's real source root.

```css
/* src/index.css */
@import "cliver-playbook-app-basic/styles/index.css";

/* The app's own sources. Automatic detection already covers src/, but the
   explicit root documents the composition. */
@source "../src";

/* One line per additional package. Point at the real installed directory. */
@source "../node_modules/cliver-playbook-app-user/src";
@source "../node_modules/cliver-playbook-app-rag/src";
@source "../node_modules/cliver-playbook-app-mcp/src";
```

Why the paths matter:

- Tailwind v4's automatic content detection is rooted at the app and does not
  look inside installed packages. A package's utilities that the app never
  names literally would be missing from the built stylesheet.
- A missing or mis-levelled `@source` fails silently — no warning, just a
  subtly unstyled page.
- `node-linker=hoisted` is what makes `node_modules/<package>` a real
  directory rather than a symlink into pnpm's store. On Tailwind 4.3.3 a
  relative `@source` naming a symlinked package path contributes nothing to
  the built CSS, with no warning; the same path as a real directory works.
  This is why the linker setting is load-bearing, not cosmetic.
- Only the stylesheet that (transitively) carries `@import "tailwindcss"` can
  declare sources; that is the app's own entry, not a second imported file.

Verify the build rather than the path. Each package has a class used only in
its own pages, so its presence in the built CSS proves the source was scanned:

```sh
pnpm build
grep -q 'break-all' dist/assets/*.css   # user package
grep -q 'max-h-80'  dist/assets/*.css   # rag package
grep -q 'max-w-48'  dist/assets/*.css   # mcp package
```

The exact utility may change between releases. If a grep stops matching,
open the package's pages, pick a utility used there and only there, and use
that instead; do not delete the gate.

The theme overrides go after the import, never before:

```css
@import "cliver-playbook-app-basic/styles/index.css";

:root,
[data-theme="light"] {
  --primary: oklch(0.55 0.15 250);
}
```

`src/styles/tokens.css` in the basic package defines every variable; override
the ones the product changes. Do not fork the package for branding.

## Project pages

Use the shared client and query cache; do not create a second axios instance.

```tsx
// src/pages/OrdersPage.tsx
import { useQuery } from "@tanstack/react-query";

import { api, apiErrorMessage } from "cliver-playbook-app-basic";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";

interface Order {
  id: number;
  status: string;
  total_cents: number;
}

export default function OrdersPage() {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["orders"],
    queryFn: async () => {
      const response = await api.get<Order[]>("/orders");
      return response.data;
    },
  });

  if (isPending) return <p>Loading…</p>;
  if (error) {
    return (
      <div>
        <p>{apiErrorMessage(error)}</p>
        <Button onClick={() => void refetch()}>Retry</Button>
      </div>
    );
  }
  return (
    <ul>
      {data.map((order) => (
        <li key={order.id}>
          {order.id} — {order.status} — {order.total_cents}
        </li>
      ))}
    </ul>
  );
}
```

Import rules:

- Package root for the wired-once surface (`api`, `createI18n`,
  `basicRoutes`, providers).
- Deep path **with the `.tsx`/`.ts` extension** for everything else:
  `cliver-playbook-app-basic/components/ui/button.tsx`. The package's
  `exports` patterns match exactly; the extension is not optional.
- No `@/` alias in project code either. Keep a file's provenance visible at
  the import site.

## Split deployment

Same-origin is the default and needs no configuration. If the API is served
from another origin, set `VITE_API_BASE_URL` at build time; the shared client
appends `/api/v1`. The MCP playground then calls `/mcp` cross-origin, so the
backend's allowed origins must cover the frontend origin. Prefer a reverse
proxy that serves both from one origin: it avoids CORS, keeps cookies and
OAuth redirects simple, and needs no `VITE_API_BASE_URL`.

## Frontend gates

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm build
```

Then the CSS sentinel greps above, and a manual pass over the first vertical
slice in the browser. A green build does not prove the page works; a working
page does not prove the styles were scanned.
