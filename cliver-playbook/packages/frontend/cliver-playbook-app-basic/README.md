# cliver-playbook-app-basic (frontend)

Frontend basics for an app built on cliver-playbook: the visual shell, theming,
i18n, an HTTP client and a demo CRUD surface to copy patterns from.

Source-only package: `exports` point straight at TypeScript sources, so the
consuming app's Vite build transpiles them — no build step, no `dist`. That is
why it is `private` (it is installed from the workspace or copied into the
project, never published) and why `react`/`react-dom` are peer dependencies
(the app owns the single React instance).

## Layout

| Path | Contents |
| --- | --- |
| `src/index.ts` | The public barrel — everything an app is expected to import from the package root. |
| `src/routes.tsx` | `basicRoutes: RouteObject[]` — the routes this package contributes. |
| `src/layout/` | `AppLayout` (parameterised nav + `headerExtra` slot) and its `NavItem` type. |
| `src/theme/` | `ThemeProvider` / `ThemeToggle` — `data-theme` attribute, `light` / `dark` / `system`. |
| `src/i18n/` | `createI18n()` (deep-merges every package's bundles) and `LanguageSwitcher`. |
| `src/locales/` | `en.json` / `zh.json` translation bundles owned by this package. |
| `src/api/` | `axios` instance with `setAuthTokenGetter()`, plus the items endpoints. |
| `src/crud/` | `DataTable` and `useCrudQueries` — the list/edit/delete pattern. |
| `src/components/ui/` | Vendored shadcn/ui primitives (Radix under the hood). |
| `src/styles/` | `index.css` (Tailwind + theme tokens) and `tokens.css` (the palettes). |
| `tooling/` | `vite.config.base.ts`, `tsconfig.base.json`, `index.html` — shared config for apps. |
| `dev/` | A minimal app that consumes the package by name; the only way to run it. |

## Using it from an app

```tsx
// app/src/main.tsx
import { createI18n } from "cliver-playbook-app-basic";
import "cliver-playbook-app-basic/styles/index.css";

createI18n();
```

```tsx
// app/src/App.tsx — the app owns the providers and the route table
const routes: RouteObject[] = [
  { element: <AppLayout />, children: basicRoutes },
  { path: "*", element: <Navigate to="/" replace /> },
];
```

Import convention: every import names its owning package — no `@/` alias, so a
file's provenance is visible at the import site and moving code between
packages is a rename.

| Specifier | Example |
| --- | --- |
| Package root (the barrel) | `cliver-playbook-app-basic` |
| Deep path, **with the file extension** | `cliver-playbook-app-basic/components/ui/button.tsx` |
| The shared tooling files | `cliver-playbook-app-basic/tooling/vite.config.base.ts` |

The extension is not optional: the package's `exports` subpath patterns are
matched exactly, so `…/components/ui/button` resolves nowhere, while
`…/button.tsx` resolves everywhere (TypeScript, Vite, esbuild) with no alias or
`paths` entry in the consuming app. Imports *inside* the package use the same
form, which keeps a file's dependencies visible after it is moved.

An app wires the package in with two lines — no bundler or compiler setup of
its own:

```jsonc
// app/tsconfig.app.json
{ "extends": "cliver-playbook-app-basic/tooling/tsconfig.base.json" }
```

```ts
// app/vite.config.ts
import { baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";
export default defineConfig(baseConfig());
```

## Development

From the workspace root (this package has no dependencies of its own to install
beyond the workspace):

```sh
pnpm install                  # once, from the repository root
pnpm --filter cliver-playbook-dev-basic dev    # the dev shell, proxying /api
pnpm --filter cliver-playbook-app-basic typecheck
pnpm --filter cliver-playbook-app-basic lint
```

`dev/` is a throwaway app: it exists so the package can be type-checked, linted
and built as a real consumer would, and so a UI change can be looked at without
spinning up a project.

## Notes

- The demo **items** surface (table, migration, CRUD page) is here as a worked
  example: an app that does not need it deletes `src/pages/ItemsPage.tsx`,
  `src/api/items.ts` and its entry in `basicRoutes`.
- `index.html` in `tooling/` is the canonical app shell — copy it into the app.
  Its inline script must stay inline (it sets `data-theme` before first paint)
  and its storage key must match `ThemeProvider`.
- `styles/index.css` carries `@source "../"`: the app's Tailwind build is
  rooted at the app, and automatic content detection skips `node_modules`, so
  the package has to name its own sources or the utilities used only here would
  be missing from the built stylesheet. Every package that ships styles needs
  its own line, and the build-time tools it imports (`tailwindcss`, the vite
  plugins) are its dev dependencies.
- Theme and language persist under the `cliver-theme` / `i18nextLng` keys.
