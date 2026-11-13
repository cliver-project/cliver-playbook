import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ChevronDownIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "cliver-playbook-app-basic/components/ui/dropdown-menu.tsx";
import { LanguageSwitcher } from "cliver-playbook-app-basic/i18n/LanguageSwitcher.tsx";
import { ErrorBoundary } from "cliver-playbook-app-basic/layout/ErrorBoundary.tsx";
import { ThemeToggle } from "cliver-playbook-app-basic/theme/ThemeToggle.tsx";

/** One header navigation entry: a route and the i18n key of its label. */
export interface NavItem {
  to: string;
  labelKey: string;
  /**
   * Match the route exactly. Needed for "/" — a prefix match would keep the
   * home entry highlighted on every page.
   */
  end?: boolean;
  /**
   * Optional second-level entries. The parent stays a link to ``to``; a
   * chevron beside it opens the submenu. This is how a package with many
   * pages keeps the header from crowding — one entry per area, pages
   * underneath.
   */
  children?: NavItem[];
}

/** This package's pages — the navigation of a basic-only app. */
export const basicNavItems: NavItem[] = [
  { to: "/", labelKey: "nav.home", end: true },
  { to: "/items", labelKey: "nav.items" },
];

export interface AppLayoutProps {
  /** Header entries; defaults to this package's pages. */
  navItems?: NavItem[];
  /**
   * Extra controls rendered beside the language and theme switchers — where a
   * composing package puts its account menu (it knows its own auth state; this
   * layout deliberately knows nothing about permissions).
   */
  headerExtra?: ReactNode;
}

/**
 * Application chrome: brand + navigation on a sticky header, language and
 * theme controls (plus anything the app adds) on the right, routed content in
 * the outlet.
 *
 * An entry with ``children`` renders as a link plus a chevron dropdown: the
 * label keeps its own route, the submenu holds the second-level pages, and
 * the parent reads as active whenever any child route is open.
 *
 * The outlet is wrapped in an `ErrorBoundary`, so a render or lazy-chunk
 * failure below the layout shows the recoverable error panel instead of a
 * blank page. The boundary resets when the pathname changes: navigating away
 * from a crashed page is enough to recover. Errors thrown by the layout's own
 * header are outside that boundary by design.
 *
 * Used as the app's single layout route, so a composing app passes the header
 * entries of every package it includes:
 *
 *     { element: <AppLayout navItems={[...basicNavItems, ...userNavItems]} />,
 *       children: [...basicRoutes, ...userRoutes] }
 */
export function AppLayout({ navItems = basicNavItems, headerExtra }: AppLayoutProps) {
  const { t } = useTranslation();
  const location = useLocation();

  const linkClass = (isActive: boolean) =>
    isActive ? "text-foreground font-medium" : "text-muted-foreground hover:text-foreground";

  return (
    <div className="min-h-svh">
      <header className="bg-background/80 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <span className="text-base font-semibold tracking-tight">{t("app.title")}</span>
          <nav className="flex items-center gap-4 text-sm">
            {navItems.map((item) =>
              item.children && item.children.length > 0 ? (
                <div key={item.to} className="flex items-center gap-0.5">
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => linkClass(isActive)}
                  >
                    {t(item.labelKey)}
                  </NavLink>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={t(item.labelKey)}
                        className={linkClass(
                          location.pathname === item.to ||
                            location.pathname.startsWith(`${item.to}/`),
                        )}
                      >
                        <ChevronDownIcon className="size-3.5" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      {item.children.map((child) => (
                        <DropdownMenuItem key={child.to} asChild>
                          <NavLink
                            to={child.to}
                            end={child.end}
                            className={({ isActive }) =>
                              isActive ? "text-foreground font-medium" : "text-muted-foreground"
                            }
                          >
                            {t(child.labelKey)}
                          </NavLink>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              ) : (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => linkClass(isActive)}
                >
                  {t(item.labelKey)}
                </NavLink>
              ),
            )}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
            {headerExtra}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <ErrorBoundary resetKey={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default AppLayout;
