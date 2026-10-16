import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, useRoutes, type RouteObject } from "react-router-dom";

import {
  AppLayout,
  ThemeProvider,
  Toaster,
  basicRoutes,
  queryClient,
} from "cliver-playbook-app-basic";

/**
 * The app (ADR-0008): providers outside, one route table inside.
 *
 * The route table is the composition point — every package contributes its
 * routes, and this shell decides the chrome and the provider order. Query
 * cache → theme → router: components may use `useQuery` and `useTheme` and
 * link between routes anywhere below.
 *
 * `useRoutes` rather than `<Routes>` because the packages hand over
 * `RouteObject[]` values: JSX `<Route>` children must be elements.
 */
const routes: RouteObject[] = [
  { element: <AppLayout />, children: basicRoutes },
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
          <AppRoutes />
          {/* Toast host: rendered once, above the routes so toasts survive navigation. */}
          <Toaster />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
