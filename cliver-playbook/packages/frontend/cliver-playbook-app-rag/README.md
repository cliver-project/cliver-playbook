# cliver-playbook-app-rag (frontend)

Source-only React package for the RAG knowledge base: document upload with
per-stage selection, chunk preview, indexing, retrieval-only search, grounded
chat with citations, and an administrator view.

Like every frontend package here it has no build step. `exports` points at the
TypeScript sources, the consuming app's Vite build transpiles them, and deep
imports carry the source extension:

```tsx
import { ragRoutes, ragNavItems, ragTranslations } from "cliver-playbook-app-rag";
import RagDocumentsPage from "cliver-playbook-app-rag/pages/RagDocumentsPage.tsx";
```

## Composition

```tsx
// routes: children of the authenticated layout
{ element: <AuthAppLayout extraNavItems={[...mcpNavItems, ...ragNavItems]} />,
  children: [...basicRoutes, ...userRoutes, ...mcpRoutes, ...ragRoutes] }

// i18n: pass the bundle alongside the other packages'
createI18n(userTranslations, mcpTranslations, ragTranslations);
```

`dev/` is a self-contained shell that consumes this package by name (basic +
user + rag). The mcp dev shell composes it too, which is the reference wiring
for a full project.

## Tailwind

The app owns its Tailwind entry. Because the scanner skips `node_modules` and
does not follow symlinks, the app must name this package's real source root:

```css
@import "cliver-playbook-app-basic/styles/index.css";
@source "../../../cliver-playbook-app-rag/src";
```

A missing or mis-levelled `@source` fails silently — verify with a build and
grep the output CSS for a utility that only the RAG pages use.

## Pages

| Route | Permission | Purpose |
| --- | --- | --- |
| `/rag/documents` | `rag:documents:read` | Upload, choose chunker/embedder, preview chunks, index, list documents |
| `/rag/chat` | `rag:chat:read` | Ask a grounded question, inspect citations, or run retrieval only; the query embedder is selectable per call |
| `/admin/rag` | `rag:admin:read` | Whole-corpus view with lifecycle state and failure details |

Stage dropdowns are populated from `GET /api/v1/rag/stages`, so the server's
registries are the only list of available chunkers, embedders, retrievers,
rerankers and LLMs. The UI never hardcodes them.
