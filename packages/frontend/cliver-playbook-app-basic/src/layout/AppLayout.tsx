import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { LanguageSwitcher } from "cliver-playbook-app-basic/i18n/LanguageSwitcher.tsx";
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
 * Used as the app's single layout route, so a composing app passes the header
 * entries of every package it includes:
 *
 *     { element: <AppLayout navItems={[...basicNavItems, ...userNavItems]} />,
 *       children: [...basicRoutes, ...userRoutes] }
 */
export function AppLayout({ navItems = basicNavItems, headerExtra }: AppLayoutProps) {
  const { t } = useTranslation();

  return (
    <div className="min-h-svh">
      <header className="bg-background/80 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <span className="text-base font-semibold tracking-tight">{t("app.title")}</span>
          <nav className="flex items-center gap-4 text-sm">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  isActive ? "text-foreground font-medium" : "text-muted-foreground"
                }
              >
                {t(item.labelKey)}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
            {headerExtra}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}

export default AppLayout;
