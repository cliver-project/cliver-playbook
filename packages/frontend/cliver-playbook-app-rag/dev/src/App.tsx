import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, useRoutes, type RouteObject } from "react-router-dom";

import { ThemeProvider, Toaster, basicRoutes, queryClient } from "cliver-playbook-app-basic";
import { ragNavItems, ragRoutes, ragStandaloneRoutes } from "cliver-playbook-app-rag";
import { AuthAppLayout, AuthProvider, userRoutes, userStandaloneRoutes } from "cliver-playbook-app-user";

/**
 * The composed RAG app: basic chrome and pages, the identity package's session
 * provider and account pages, and this package's knowledge-base pages — no
 * package edited to meet another.
 *
 * `AuthAppLayout` is the layout route for everything behind a session;
 * `extraNavItems` is how a package contributes header entries it owns, and
 * the layout filters them against the viewer's permissions. Unknown paths fall
 * back to the home page.
 */
const routes: RouteObject[] = [
  {
    element: <AuthAppLayout extraNavItems={ragNavItems} />,
    children: [...basicRoutes, ...userRoutes, ...ragRoutes],
  },
  ...userStandaloneRoutes,
  ...ragStandaloneRoutes,
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
