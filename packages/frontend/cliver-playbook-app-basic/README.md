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
| `src/routes.tsx` | `basicRoutes: RouteObject[]` — the routes this package contributes — plus `lazyRoute()`, the Suspense-backed lazy-route helper. |
| `src/layout/` | `AppLayout` (parameterised nav + `headerExtra` slot, its `NavItem` type) and the `ErrorBoundary` that wraps its outlet. |
| `src/theme/` | `ThemeProvider` / `ThemeToggle` — `data-theme` attribute, `light` / `dark` / `system`. |
| `src/i18n/` | `createI18n()` (deep-merges every package's bundles) and `LanguageSwitcher`. |
| `src/locales/` | `en.json` / `zh.json` translation bundles owned by this package. |
| `src/api/` | `axios` instance with `setAuthTokenGetter()`, the items endpoints, and the shared `Page<T>` envelope types. |
| `src/crud/` | `DataTable`, `useCrudQueries` (list/edit/delete) and `usePagedQuery` (offset pagination). |
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

### Lazy routes and error recovery

`AppLayout` wraps its `<Outlet />` in `ErrorBoundary`: a render, lifecycle, or
lazy-chunk failure below the layout shows a localized panel with retry and
reload actions instead of a blank page. The boundary resets when the pathname
changes, so navigating away from a crashed page recovers. Render another
boundary with a custom `fallback` (or an `onError` reporter) where a page needs
its own scoped treatment.

Project pages opt into route-level code splitting with `lazyRoute()`:

```tsx
import { lazyRoute } from "cliver-playbook-app-basic";

const ordersRoutes: RouteObject[] = [
  lazyRoute(() => import("./pages/OrdersPage.tsx"), { path: "orders" }),
  lazyRoute(() => import("./pages/OrderDetailPage.tsx"), {
    path: "orders/:id",
    // The wrapper runs before the chunk is requested, so an unauthorized
    // viewer never downloads the page.
    wrap: (page) => <RequirePerm code="orders:read">{page}</RequirePerm>,
  }),
];
```

A route is either `{ path }` or `{ index: true }`; the helper types enforce
one of the two. The page module default-exports a no-props component (route
params come from `useParams`, as usual), and `fallback` overrides the default
localized loading panel. The package's own `basicRoutes` uses `lazyRoute`, so
the demo pages are the worked example.

### Pagination

API modules type a paginated response as `Page<Row>` — the same four fields as
the backend envelope: `items`, `total`, `limit`, `offset`. `usePagedQuery`
owns the offset, appends the window to the query key, and keeps the previous
page visible while the next one loads:

```tsx
import { usePagedQuery } from "cliver-playbook-app-basic/crud/usePagedQuery.ts";

const page = usePagedQuery({
  queryKey: ["audit", event, username], // filter identity only
  resetKey: `${event}\u0000${username}`, // an edit rewinds to page one
  pageSize: 50,
  queryFn: ({ limit, offset }) => listAudit({ event, username, limit, offset }),
});

page.items; // rows in this window
page.total; // full filtered count
page.from; // 1-based range, 0..0 when empty
page.to;
page.canPrev; // pager state
page.canNext;
page.prevPage;
page.nextPage;
```

The hook also steps back a page when the current window becomes empty (rows
deleted elsewhere). The backend's `Page[T]` lives in
`cliver_playbook.app.basic.schemas.pagination`; the user package's audit page
is the worked example.

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
pnpm --filter cliver-playbook-app-basic test
```

Unit tests use Vitest with jsdom and live next to the source they cover
(`src/**/*.test.tsx`). The build and dev shell still type-check the package as
a consumer would; the test harness is for isolated helpers such as `lazyRoute`
and `usePagedQuery`.

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
  rooted at the app, and automatic content detection does not look inside an
  installed package, so the package has to name its own sources or the
  utilities used only here would be missing from the built stylesheet. That
  line covers this package; a package added on top of it is named by the app's
  own Tailwind entry (`@import` this stylesheet, then one `@source` per
  package) — see the user package's README. Only the file that carries
  `@import "tailwindcss"` can declare sources, and the scanner does not follow
  symlinks, so the extra paths must be real directories. The build-time tools
  the stylesheet imports (`tailwindcss`, the vite plugins) are this package's
  dev dependencies.
- Theme and language persist under the `cliver-theme` / `i18nextLng` keys.
