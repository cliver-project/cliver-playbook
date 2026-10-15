import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

/**
 * Application chrome: brand + navigation on a sticky header, language and
 * theme controls on the right, routed content in the outlet. Later templates
 * extend the nav with permission-gated entries (user-management admin pages).
 */
export default function AppLayout() {
  const { t } = useTranslation();

  return (
    <div className="min-h-svh">
      <header className="bg-background/80 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <span className="text-base font-semibold tracking-tight">{t("app.title")}</span>
          <nav className="flex items-center gap-4 text-sm">
            <NavLink
              to="/"
              className={({ isActive }) =>
                isActive ? "text-foreground font-medium" : "text-muted-foreground"
              }
            >
              {t("nav.home")}
            </NavLink>
            <NavLink
              to="/items"
              className={({ isActive }) =>
                isActive ? "text-foreground font-medium" : "text-muted-foreground"
              }
            >
              {t("nav.items")}
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
