# ADR-0008: Frontend platform and libraries

**Status:** Accepted (2026-10-15; write-up 2026-10-17 — cited throughout the frontend
packages). Amended 2026-10-16 (source-only packages, after the package split).
**Context:** The frontend is a client-only SPA over a FastAPI REST API. The stack
decision therefore turns on one question — which option is *simpler* — plus a standing
rule: cross-cutting concerns (HTTP, auth transport, i18n, theming, realtime) use
mature libraries, never hand-rolled equivalents.

## Decision

1. **Vite, not Next.js.** Next's value lives on the server (SSR, RSC, route handlers);
   here the server is FastAPI, so a Next app would use only file-based routing while
   paying for RSC discipline and a heavier build. React 19 + TypeScript + Vite, with
   Tailwind v4 for styling and vendored shadcn/ui primitives (Radix under the hood) as
   the component base — vendored rather than a dependency so a project can edit them,
   and so a fresh checkout builds with no registry access for the primitives.

2. **HTTP through `axios` with interceptors.** The interceptor is the library's own
   extension point: bearer injection reads a registered token getter, and the response
   policy maps 401 and `must_change_password` (403) onto the auth pages. The client
   module itself stays auth-agnostic — the identity package registers both hooks
   (`setAuthTokenGetter`, `installAuthClient()`), so an app without authentication
   uses the same client. Server state goes through **TanStack Query** (cache,
   invalidation, retries) instead of hand-written loading/error state; React context
   holds only session state.

3. **i18n with `i18next` + `react-i18next`.** A single initializer, language detected
   from the browser and persisted, `en` and `zh` shipped from the start as separate
   JSON bundles. **No UI string is written inline**: components render keys. Adding a
   language is a new JSON file, nothing else.

4. **Theming through CSS variables and a `data-theme` attribute** (`light` / `dark` /
   `system`), with the palettes in `tokens.css` aligned to the shadcn variables, and an
   inline script in `index.html` that sets the attribute before first paint — the
   no-flash requirement is why that script cannot be a module import.

5. **Realtime is a recipe, not shipped code.** No WebSocket endpoint or client is in
   the packages: an app that needs one adds a FastAPI WS endpoint and a hook library
   (e.g. `react-use-websocket`) rather than adopting speculative infrastructure.

6. **Amendment 2026-10-16 — the frontend ships as source-only packages.** Each package
   exposes its TypeScript sources directly (`"exports": {".": "./src/index.ts",
   "./*": "./src/*"}`), is `private` (consumed from this repository, never published)
   and treats `react`/`react-dom` as peer dependencies, since the app owns the single
   React instance. There is no `dist` and no build step for a package: the app's Vite
   build transpiles it.

   Two mechanisms make that work, both found by experiment rather than by reading:

   - **Deep paths carry the source extension** (`…/components/ui/button.tsx`).
     `exports` subpath patterns are matched exactly — `…/button` resolves nowhere,
     in TypeScript and in Vite alike. The convention costs one `.tsx` per import and
     buys **zero consumer configuration**: no `@/` alias, no `paths`, no bundler
     alias, and the same form works cross-package and inside a package, so a file's
     provenance is visible at the import site.
   - **Tailwind content scanning must be told about each package.** Automatic source
     detection is rooted at the app and skips installed packages, so the app owns a
     Tailwind entry that imports the basic stylesheet and lists every additional
     package's source root with `@source`. `@source` only takes effect in the file
     that carries `@import "tailwindcss"` (a fragment that merely imports the
     stylesheet is inert), and the scanner does **not** follow symlinks — the paths
     must be the packages' real directories. **A wrong path fails silently**: the
     symptom is utilities missing from the built CSS, so the wiring is verified by
     probing the built stylesheet for a utility used only in a given package.

   Composition seams, mirroring the backend's router list: each package exports a
   `RouteObject[]`, its nav entries (with the permission that makes each reachable),
   and its own translation bundle; the app spreads the route arrays into one table and
   passes the bundles to `createI18n(...)`, which deep-merges them per language — which
   is what lets three packages contribute to one `nav` tree. Locale keys are split by
   owner, so the same key never appears in two packages.

## Consequences

- One TypeScript program spans app and packages: a consumer's `tsc` type-checks the
  package sources. Ambient declarations therefore do **not** travel with an import
  (a source-only package's `env.d.ts` is outside the consumer's `include`) — the
  package that declares `import.meta.env` must reference its own declaration file.
- A package's build-time tooling (Tailwind, the Vite plugins) are the package's own
  dev dependencies, because a `tooling/` file resolves plugins from its own directory.
- Editing a package is immediately visible in every app — the usual benefit of
  source-only distribution, and the reason it is safe here: consumption is from this
  repository, where a breaking change and its consumers are one commit apart.

## Alternatives considered

- **Next.js**: rejected (see 1). If a project ever needs SSR or SEO, that is a separate
  site with its own choice; it does not move this app.
- **Building the packages to `dist` and publishing artifacts**: rejected — a build step
  per package, a stale-artifact failure mode, and source maps across a boundary, for
  no consumer that exists.
- **A `@/` alias convention inside packages**: rejected — it hides which package a file
  comes from and makes moving code between packages a silent change of meaning.
- **A component library dependency instead of vendored primitives**: rejected — the
  point of vendoring is that the components are ours to change.
- **Hand-rolled fetch wrappers, i18n, or theme state**: rejected by the standing rule —
  these are exactly the problems mature libraries already solved.
