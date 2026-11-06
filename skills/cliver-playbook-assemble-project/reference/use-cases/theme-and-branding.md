# Brand the shell (colors, title, copy)

## Use when

The product needs its own name, theme colors, radius, login copy, or favicon.
Branding is configuration and the project's own stylesheet; it is never a fork
of a playbook package.

Profile: any.

## Do

### 1. Set the product name in both layers

```yaml
# app.yaml
app_name: Example App
```

```json
// src/locales/en.json (and zh.json)
{ "app": { "title": "Example App", "tagline": "Operations console" } }
```

The backend `app_name` is the FastAPI title; the frontend `app.title` is the
visible shell title. Keep them consistent.

### 2. Override design tokens after the package import

```css
/* src/index.css */
@import "cliver-playbook-app-basic/styles/index.css";

:root,
[data-theme="light"] {
  --primary: oklch(0.55 0.16 255);
  --primary-foreground: oklch(0.985 0 0);
  --radius: 0.75rem;
}

[data-theme="dark"] {
  --primary: oklch(0.72 0.14 255);
  --primary-foreground: oklch(0.145 0 0);
}
```

Override the variables defined in the package's `styles/tokens.css`
(`--primary`, `--background`, `--foreground`, `--muted`, `--border`, `--ring`,
`--radius`, and so on). The order matters: the import comes first, the
overrides after it.

### 3. Replace visible copy in the project bundle

`createI18n` deep-merges bundles and the project bundle is passed last, so it
wins on conflicts. Override package keys instead of copying files:

```json
{
  "auth": { "signIn": "Sign in to Example" },
  "home": { "welcome": "Welcome to Example" }
}
```

Keep the key shape; a missing key renders as the key itself.

### 4. Replace the favicon and document title

Copy `cliver-playbook-app-basic/tooling/index.html` into the app, then change
`<title>` and `public/favicon.svg`. Keep the inline no-flash theme script
inline and keep its storage key (`cliver-theme`) in sync with `ThemeProvider`.

### 5. Brand SSO buttons through provider metadata

The login page renders the backend's provider metadata. Set
`oidc.providers.<key>.labels`, `.icon`, and `.brand_color`; do not edit the
login page. See `reference/use-cases/configure-oidc-login.md`.

## Verify

```sh
pnpm typecheck
pnpm lint
pnpm build
```

Load the page in light and dark mode, hard-reload once to confirm the no-flash
script applies the stored theme before paint, and inspect the built CSS for the
overridden values. Check the provider buttons with an icon and with only a
color.

## Pitfalls

- **Do not fork the package for colors.** Override the tokens.
- **Define both theme blocks.** A light-only override leaves dark mode with an
  inconsistent primary.
- **The import must come before the overrides.** Tailwind's `@theme` mapping
  reads the variables at build time from the token file; later overrides are
  what the browser applies.
- **`@source` paths are separate from theming.** A missing `@source` silently
  drops utilities used only in a package, which looks like a styling bug.
- **Theme and language storage keys are part of the shell contract.**
  `cliver-theme` and `i18nextLng` must match the providers.
- **Do not put provider secrets in `app.yaml`.** Brand metadata is public;
  credentials are not.

## Source of truth

- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/styles/tokens.css`
  — every token name.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/styles/index.css`
  — the Tailwind mapping and `@source`.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/theme/`
  — `ThemeProvider` / `ThemeToggle`.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/tooling/index.html`
  — the canonical shell.
- Deep dive: `reference/frontend-composition.md` section "The Tailwind entry".
