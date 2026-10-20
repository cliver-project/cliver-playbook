import type { AuthedNavItem } from "cliver-playbook-app-user/layout/AuthAppLayout.tsx";

/**
 * The header entries this package adds to the app's navigation.
 *
 * Each entry names the permission that makes its page reachable; the layout
 * filters the list against the viewer's permissions. The page and the gate
 * live together here on purpose — the package that owns a page also owns the
 * answer to "who can see it", and the server rejects the underlying calls
 * whatever the header renders.
 */
export const ragNavItems: AuthedNavItem[] = [
  { to: "/rag/documents", labelKey: "nav.ragDocuments", perm: "rag:documents:read" },
  { to: "/rag/chat", labelKey: "nav.ragChat", perm: "rag:chat:read" },
  { to: "/admin/rag", labelKey: "nav.ragAdmin", perm: "rag:documents:read" },
];
