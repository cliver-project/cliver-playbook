import { Suspense, lazy, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { RouteObject } from "react-router-dom";

/** A lazily imported page: a module whose default export is the component. */
type LazyPageModule = { default: ComponentType<Record<string, never>> };

interface LazyRouteCommonOptions {
  /**
   * Shown while the chunk loads. Defaults to the package's localized loading
   * panel; pass a skeleton here when the page has a known shape.
   */
  fallback?: ReactNode;
  /**
   * Wraps the lazy page — e.g. a permission gate. The wrapper is evaluated
   * before the chunk is requested, so an unauthorized viewer never downloads
   * the page.
   */
  wrap?: (page: ReactNode) => ReactNode;
}

/**
 * A lazy route is either the index route or a path route; one of the two is
 * required so a route object can never be silently unmatched.
 */
export type LazyRouteOptions =
  | (LazyRouteCommonOptions & { index: true; path?: never })
  | (LazyRouteCommonOptions & { index?: false; path: string });

function RouteLoading() {
  const { t } = useTranslation();

  return (
    <div
      role="status"
      aria-live="polite"
      className="text-muted-foreground flex min-h-40 items-center justify-center text-sm"
    >
      {t("common.loading")}
    </div>
  );
}

/**
 * Build a route whose page is a separate chunk, with a Suspense fallback.
 *
 * `React.lazy` starts the import on the first render and `Suspense` shows the
 * fallback until it resolves. A failed chunk load (for example an old build
 * after a deploy) rejects during render, so the nearest `ErrorBoundary` — the
 * one `AppLayout` puts around its outlet — catches it and offers a reload.
 *
 *     export const ordersRoutes: RouteObject[] = [
 *       lazyRoute(() => import("./pages/OrdersPage.tsx"), { path: "orders" }),
 *       lazyRoute(() => import("./pages/OrderDetailPage.tsx"), {
 *         path: "orders/:id",
 *         wrap: (page) => <RequirePerm code="orders:read">{page}</RequirePerm>,
 *       }),
 *     ];
 *
 * The page module must default-export a component that takes no props; route
 * params are read with `useParams`, as for any other route element.
 */
export function lazyRoute(load: () => Promise<LazyPageModule>, options: LazyRouteOptions): RouteObject {
  const LazyPage = lazy(load);
  const { fallback = <RouteLoading />, wrap } = options;
  const content = (
    <Suspense fallback={fallback}>
      <LazyPage />
    </Suspense>
  );
  const element = wrap ? wrap(content) : content;

  if (options.index) {
    return { index: true, element };
  }
  return { path: options.path, element };
}

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
 * added to or removed from a project without editing an app file. The demo
 * pages use `lazyRoute`, so the package's route table is also the worked
 * example of code splitting.
 */
export const basicRoutes: RouteObject[] = [
  lazyRoute(() => import("cliver-playbook-app-basic/pages/HomePage.tsx"), { index: true }),
  lazyRoute(() => import("cliver-playbook-app-basic/pages/ItemsPage.tsx"), { path: "items" }),
];
