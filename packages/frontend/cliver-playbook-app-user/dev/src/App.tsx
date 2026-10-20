import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, useRoutes, type RouteObject } from "react-router-dom";

import { ThemeProvider, Toaster, basicRoutes, queryClient } from "cliver-playbook-app-basic";
import {
  AuthAppLayout,
  AuthProvider,
  userRoutes,
  userStandaloneRoutes,
} from "cliver-playbook-app-user";

/**
 * The app (ADR-0008): providers outside, one route table inside.
 *
 * Two packages meet here and neither is edited to do it: the basic package
 * contributes the chrome (`AppLayout`), the home/items pages and the client
 * setup; this one contributes the session provider, the auth layout and the
 * account pages. `AuthAppLayout` is the layout route for everything that needs
 * a session, and the standalone auth pages sit beside it, outside the chrome.
 *
 * `useRoutes` rather than `<Routes>` because the packages hand over
 * `RouteObject[]` values: JSX `<Route>` children must be elements.
 */
const routes: RouteObject[] = [
  { element: <AuthAppLayout />, children: [...basicRoutes, ...userRoutes] },
  ...userStandaloneRoutes,
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
