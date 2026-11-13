import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, useRoutes, type RouteObject } from "react-router-dom";

import { ThemeProvider, Toaster, basicRoutes, queryClient } from "cliver-playbook-app-basic";
import { ragRoutes, ragStandaloneRoutes } from "cliver-playbook-app-rag";
import { govNavItems, govRoutes, govStandaloneRoutes } from "cliver-playbook-app-rag-governance";
import {
  AuthAppLayout,
  AuthProvider,
  userRoutes,
  userStandaloneRoutes,
  type AuthedNavItem,
} from "cliver-playbook-app-user";

/**
 * The composed governance demo app: basic chrome and pages, the identity
 * package's session provider and account pages, the ungoverned knowledge-base
 * pages, and this package's governance loop pages — no package edited to meet
 * another.
 *
 * The rag pages are part of the story, not a leftover: the ungoverned
 * documents/chat pages are where an operator sees the "before" (upload →
 * search immediately), and the governance pages are the loop that gates the
 * same corpus. The backend serves both router sets from one app.
 *
 * Navigation keeps the header calm by grouping: the knowledge-base pages sit
 * under one "Knowledge base" entry (documents is the parent page; chat and
 * the corpus admin are its children) and the governance loop under its own.
 *
 * `AuthAppLayout` is the layout route for everything behind a session;
 * `extraNavItems` is how a package contributes header entries it owns, and
 * the layout filters them — children included — against the viewer's
 * permissions.
 */
const extraNavItems: AuthedNavItem[] = [
  {
    to: "/rag/documents",
    labelKey: "nav.ragDocuments",
    perm: "rag:documents:read",
    children: [
      { to: "/rag/chat", labelKey: "nav.ragChat", perm: "rag:chat:read" },
      { to: "/admin/rag", labelKey: "nav.ragAdmin", perm: "rag:documents:read" },
    ],
  },
  ...govNavItems,
];

const routes: RouteObject[] = [
  {
    element: <AuthAppLayout extraNavItems={extraNavItems} />,
    children: [...basicRoutes, ...userRoutes, ...ragRoutes, ...govRoutes],
  },
  ...userStandaloneRoutes,
  ...ragStandaloneRoutes,
  ...govStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];

function AppRoutes() {
  return useRoutes(routes);
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
            <Toaster />
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
