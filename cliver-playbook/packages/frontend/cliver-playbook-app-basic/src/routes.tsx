import type { RouteObject } from "react-router-dom";

import HomePage from "cliver-playbook-app-basic/pages/HomePage.tsx";
import ItemsPage from "cliver-playbook-app-basic/pages/ItemsPage.tsx";

/**
 * This package's contribution to the application's route table.
 *
 * The paths are relative: the routes are rendered as children of the app's
 * layout route, which owns the chrome (`AppLayout`). A composing app spreads
 * every package's routes into that children array::
 *
 *     const routes: RouteObject[] = [
 *       { element: <AppLayout />, children: [...basicRoutes, ...userRoutes] },
 *     ];
 *
 * Keeping routes here (rather than in the app) is what lets a package be
 * added to or removed from a project without editing an app file.
 */
export const basicRoutes: RouteObject[] = [
  { index: true, element: <HomePage /> },
  { path: "items", element: <ItemsPage /> },
];
