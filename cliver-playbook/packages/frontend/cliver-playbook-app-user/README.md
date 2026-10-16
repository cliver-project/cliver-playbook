# cliver-playbook-app-user (frontend)

The account surface of an app built on cliver-playbook: sign-in (password and
OIDC), the session policy, self-service profile, and the RBAC admin pages.

Source-only package, like its basic-package dependency: `exports` point
straight at TypeScript sources, so the consuming app's Vite build transpiles
them — no build step, no `dist`. It is `private` (installed from the workspace
or copied into the project, never published) and `react`/`react-dom` are peer
dependencies (the app owns the single React instance).

## Layout

| Path | Contents |
| --- | --- |
| `src/index.ts` | The public barrel — what an app composes with. |
| `src/routes.tsx` | `userStandaloneRoutes` (outside the chrome) and `userRoutes` (layout children). |
| `src/layout/AuthAppLayout.tsx` | The layout route: basic `AppLayout` + the session guard + the account menu. |
| `src/auth/session.ts` | Token storage and `installAuthClient()` — the client half of the session policy. |
| `src/components/auth/` | `AuthProvider`/`useAuth`, `AuthShell` (standalone-page chrome), `RequirePerm`. |
| `src/api/auth.ts` | Every auth/admin endpoint, as typed wrappers over the shared client. |
| `src/pages/` | Sign-in, password gate, OIDC callback, OAuth 2.1 authorize, profile. |
| `src/pages/admin/` | Users, roles, OAuth clients/grants, audit log. |
| `src/locales/` | `en.json` / `zh.json` — the keys this package owns, plus `userTranslations`. |
| `dev/` | A composed app (basic + user) that consumes both packages by name. |

## Using it from an app

```tsx
// app/src/main.tsx
import { createI18n } from "cliver-playbook-app-basic";
import { installAuthClient, userTranslations } from "cliver-playbook-app-user";
import "./index.css"; // the app's Tailwind entry — see below

installAuthClient(); // axios interceptors are global: before the first request
createI18n(userTranslations);
```

```tsx
// app/src/App.tsx — the app owns the providers and the route table
const routes: RouteObject[] = [
  { element: <AuthAppLayout />, children: [...basicRoutes, ...userRoutes] },
  ...userStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];
```

The routes and the header entries come from the packages, so adding this
package to a project never means editing an app file: `AuthAppLayout` gates the
layout on the session and shows the admin entries the viewer's permissions
allow. Import convention, including the extension on deep paths, is the basic
package's — see its README.

### The app's stylesheet

Tailwind's automatic source detection is rooted at the app and does not look
inside an installed package, so the app's own Tailwind entry names the source
root of every package it uses:

```css
/* app/src/index.css — the theme and Tailwind itself come from the basic package */
@import "cliver-playbook-app-basic/styles/index.css";
@source "../../cliver-playbook-app-user/src";
```

The `@source` path must be the package's **real** directory: the scanner does
not follow symlinks, so pointing at `node_modules/cliver-playbook-app-user`
under a linked install is silently ignored (utilities used only in this package
then go missing from the built stylesheet). Copying the package's sources into
the project — the usual install model here — makes the path a plain relative
one.

## Development

From the workspace root:

```sh
pnpm install
pnpm --filter cliver-playbook-dev-user dev          # the composed shell, proxying /api
pnpm --filter cliver-playbook-app-user typecheck
pnpm --filter cliver-playbook-app-user lint
```

`dev/` is a throwaway app: it exists so the package can be type-checked, linted
and built as a real consumer would, and so a UI change can be looked at without
spinning up a project. It is also the reference for how the pieces compose —
providers, route table, Tailwind entry, auth client install.

## Notes

- `installAuthClient()` is idempotent and registers two behaviours on the
  shared client: bearer injection from localStorage (key `cliver-token`) and
  the response policy — 401 clears the token and reloads to `/login`, 403 with
  `detail.code === "must_change_password"` goes to `/change-password`. Both are
  suppressed on the auth pages themselves, which exist to handle those errors.
- `AuthProvider` holds session state only (~100 lines, no network logic beyond
  `/me`); server state belongs to TanStack Query, and permissions it exposes
  are for display — the server enforces every call.
- Locale keys are split by owner: this package ships `auth`, `admin`, `profile`
  and its `nav.*` entries; `app`, `common`, `nav.home`, `nav.items` and the demo
  `home`/`items` trees stay in the basic package. The bundles are deep-merged,
  which is what lets both packages contribute to one `nav` tree.
