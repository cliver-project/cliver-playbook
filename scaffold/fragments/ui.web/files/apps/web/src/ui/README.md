# UI seam

Pages and feature code import visual components only from `src/ui`. This
directory is the project's replacement point:

- `index.ts` is the public surface.
- `chat.tsx`, `ProductList.tsx`, `ProductEditor.tsx` and `feedback.tsx` are the
  reference implementations.
- The default exports re-use the playbook's primitives; a project can replace
  the export or the whole file without touching feature data flow.

`pnpm seam-check` (part of `make web-check`) rejects a deep playbook visual
import from `src/pages` or `src/features`. Import from `../../ui` instead.

## Swap recipe

1. Change the component you want in this directory, or wrap the existing one.
2. Keep the public props in `index.ts` stable, or update the feature that
   renders it.
3. Run `pnpm typecheck`, `pnpm lint`, `pnpm seam-check` and `pnpm build`.

Direct feature routes stay available; the chat surface is one form of UI, not
the only entry point.
