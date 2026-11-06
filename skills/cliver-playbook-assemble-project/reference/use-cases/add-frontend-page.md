# Add a frontend page

## Use when

The project needs a new routed page and an optional navigation entry.
`AppLayout` already wraps the outlet in `ErrorBoundary`, so a page gets
recoverable render and lazy-chunk failures without extra code.

Profile: any. For `minimal`, omit the auth-specific pieces.

## Do

### 1. Create a default-export page

```tsx
// src/pages/OrdersPage.tsx
export default function OrdersPage() {
  return <h1>Orders</h1>;
}
```

A lazy route module must default-export a component that takes no props. Read
route params with `useParams` inside the page, not by adding props.

### 2. Add a lazy route

```tsx
// src/routes.tsx
import type { RouteObject } from "react-router-dom";

import { lazyRoute } from "cliver-playbook-app-basic";
import { RequirePerm, type AuthedNavItem } from "cliver-playbook-app-user";

export const projectRoutes: RouteObject[] = [
  lazyRoute(() => import("./pages/OrdersPage.tsx"), {
    path: "orders",
    // The wrapper runs before the chunk is requested, so an unauthorized
    // viewer never downloads the page.
    wrap: (page) => <RequirePerm code="orders:read">{page}</RequirePerm>,
  }),
];

export const projectNavItems: AuthedNavItem[] = [
  { to: "/orders", labelKey: "nav.orders", perm: "orders:read" },
];
```

- Route paths inside the layout's `children` are relative (`"orders"`).
- `NavItem.to` is absolute (`"/orders"`).
- For `minimal`, use `lazyRoute` without `wrap`, type the nav list as
  `NavItem[]`, and pass `navItems={[...basicNavItems, ...projectNavItems]}` to
  `AppLayout`.
- For user profiles, pass `projectNavItems` to
  `AuthAppLayout extraNavItems`; the layout already adds `basicNavItems` and
  `userNavItems` and hides entries the viewer cannot use.

### 3. Spread the data into the app route table

```tsx
// src/App.tsx — children of the layout route
children: [...basicRoutes, ...userRoutes, ...projectRoutes],
```

```tsx
// the layout element — add other packages' nav arrays here too
<AuthAppLayout extraNavItems={projectNavItems} />
```

Do not edit the package's route arrays. Composition is data.

### 4. Add the translation keys

Add to both `src/locales/en.json` and `src/locales/zh.json` (or the project's
locale files), then pass the bundle to `createI18n` last:

```json
{
  "nav": { "orders": "Orders" },
  "orders": { "title": "Orders", "empty": "No orders yet" }
}
```

A missing key renders the key itself. Use the project bundle to override
package copy rather than copying package locale files.

### 5. Add a scoped error boundary only if the page needs one

`AppLayout` already wraps its outlet in `ErrorBoundary`, reset on pathname
change. A page that needs a custom fallback can render another boundary:

```tsx
import { ErrorBoundary } from "cliver-playbook-app-basic";

<ErrorBoundary
  fallback={({ reset }) => <button onClick={reset}>Retry orders</button>}
  onError={(error, info) => report(error, info)}
>
  <OrdersTable />
</ErrorBoundary>;
```

Do not add a second boundary around every page; the layout boundary is the
default recovery surface.

## Verify

```sh
pnpm typecheck
pnpm lint
pnpm build
```

Open `/orders` directly (not only by clicking the nav link), confirm the lazy
chunk loads, and navigate away from a thrown render error: the boundary resets
on the path change. For a protected page, verify the nav entry is hidden and
the direct URL renders the permission gate for a viewer without the code.

## Pitfalls

- **Route path vs nav path:** children are relative, nav targets are absolute.
- **No `@/` alias.** Deep imports carry the `.ts`/`.tsx` extension.
- **The page must default-export a no-props component.** A named export is not
  found by `React.lazy`.
- **`RequirePerm` is a UI affordance.** The server checks the same code; never
  treat the hidden nav entry as authorization.
- **A missing translation key is visible as the key.** Add both locales when
  the project supports both.
- **`ErrorBoundary` catches render/lifecycle/lazy-chunk errors**, not event
  handler or rejected-promise errors; handle those where they occur.

## Source of truth

- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/routes.tsx`
  — `lazyRoute`.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/layout/AppLayout.tsx`
  — the outlet boundary and `NavItem`.
- `var/playbook/packages/frontend/cliver-playbook-app-user/src/layout/AuthAppLayout.tsx`
  — `AuthedNavItem` and the session-gated layout.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/README.md`
  sections "Lazy routes and error recovery" and "Pagination".
- Deep dive: `reference/frontend-composition.md` section "Project routes and
  navigation".
