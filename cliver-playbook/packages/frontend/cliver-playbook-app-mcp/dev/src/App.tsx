import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, useRoutes, type RouteObject } from "react-router-dom";

import { ThemeProvider, Toaster, basicRoutes, queryClient } from "cliver-playbook-app-basic";
import { AuthAppLayout, AuthProvider, userRoutes, userStandaloneRoutes } from "cliver-playbook-app-user";
import { mcpNavItems, mcpRoutes } from "cliver-playbook-app-mcp";
import { ragNavItems, ragRoutes, ragStandaloneRoutes } from "cliver-playbook-app-rag";

/**
 * The composed app (ADR-0008): providers outside, one route table inside.
 *
 * Four packages meet here and none is edited to do it. The basic package
 * contributes the chrome, the home/items pages and the client setup; the user
 * package contributes the session provider, the auth layout and the account
 * pages; the rag package contributes the knowledge-base pages; and this
 * package contributes the MCP pages. `AuthAppLayout` is the layout route for
 * everything that needs a session — `extraNavItems` is how a package adds
 * header entries it owns, and they are filtered against the viewer's
 * permissions like its own.
 *
 * `useRoutes` rather than `<Routes>` because the packages hand over
 * `RouteObject[]` values: JSX `<Route>` children must be elements.
 */
const routes: RouteObject[] = [
  {
    element: <AuthAppLayout extraNavItems={[...mcpNavItems, ...ragNavItems]} />,
    children: [...basicRoutes, ...userRoutes, ...ragRoutes, ...mcpRoutes],
  },
  ...userStandaloneRoutes,
  ...ragStandaloneRoutes,
  // Unknown paths fall back to the home page.
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
            {/* Toast host: rendered once, above the routes so toasts survive navigation. */}
            <Toaster />
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
