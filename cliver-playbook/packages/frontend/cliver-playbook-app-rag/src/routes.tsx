import type { RouteObject } from "react-router-dom";

import RagChatPage from "cliver-playbook-app-rag/pages/RagChatPage.tsx";
import RagDocumentsPage from "cliver-playbook-app-rag/pages/RagDocumentsPage.tsx";
import RagAdminPage from "cliver-playbook-app-rag/pages/admin/RagAdminPage.tsx";
import { RequirePerm } from "cliver-playbook-app-user/components/auth/RequirePerm.tsx";

/**
 * The pages this package contributes, as children of the app's layout route
 * (`AuthAppLayout`) — hence the relative paths: the chrome and the session
 * guard both come from there.
 *
 * Each page declares the permission its data needs through `RequirePerm`.
 * That is display gating only: the server enforces the same codes on every
 * endpoint, so an account without `rag:*` gets a clear "no access" panel
 * instead of a page that fires 403s.
 *
 * `ragStandaloneRoutes` exists for symmetry with the other packages (pages
 * outside the authenticated chrome). This package has none today — the
 * knowledge base always needs a session.
 */
export const ragRoutes: RouteObject[] = [
  {
    path: "rag/documents",
    element: (
      <RequirePerm code="rag:documents:read">
        <RagDocumentsPage />
      </RequirePerm>
    ),
  },
  {
    path: "rag/chat",
    element: (
      <RequirePerm code="rag:chat:read">
        <RagChatPage />
      </RequirePerm>
    ),
  },
  {
    path: "admin/rag",
    element: (
      <RequirePerm code="rag:admin:read">
        <RagAdminPage />
      </RequirePerm>
    ),
  },
];

export const ragStandaloneRoutes: RouteObject[] = [];
