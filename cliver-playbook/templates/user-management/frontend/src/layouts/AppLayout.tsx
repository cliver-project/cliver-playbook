import { NavLink, Outlet, useLocation, useNavigate, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/AuthContext";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Application chrome for authenticated pages: brand + navigation (admin
 * entries gated by permission), language/theme controls, user menu with
 * logout. Routed content renders in the outlet.
 *
 * The layout is also the SPA's coarse auth guard: while the session boots it
 * shows a calm placeholder, anonymous visitors are bounced to /login (with a
 * return path), and accounts the server flagged must_change_password are
 * steered to the gate page — mirroring the server-side 403 gate so both
 * sides agree.
 */
export default function AppLayout() {
  const { t } = useTranslation();
  const { status, user, hasPerm, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  if (status === "loading") {
    return (
      <div className="bg-background flex min-h-svh items-center justify-center">
        <p className="text-muted-foreground animate-pulse text-sm">{t("common.loading")}</p>
      </div>
    );
  }

  if (status === "anonymous") {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  }

  if (user?.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }

  const navItems = [
    { to: "/", label: t("nav.home"), perm: null as string | null },
    { to: "/items", label: t("nav.items"), perm: null as string | null },
    { to: "/users", label: t("nav.users"), perm: "user:read" },
    { to: "/roles", label: t("nav.roles"), perm: "role:read" },
    { to: "/oauth", label: t("nav.oauth"), perm: "oauth:read" },
    { to: "/audit", label: t("nav.audit"), perm: "audit:read" },
  ].filter((item) => item.perm === null || hasPerm(item.perm));

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

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
                className={({ isActive }) =>
                  isActive ? "text-foreground font-medium" : "text-muted-foreground"
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="ml-2 gap-2">
                  <span className="max-w-32 truncate">{user?.display_name || user?.username}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel className="font-mono text-xs">
                  {user?.username}
                  {user?.role_codes.length ? ` · ${user.role_codes.join(", ")}` : ""}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/profile")}>
                  {t("nav.profile")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void handleLogout()}>
                  {t("auth.signOut")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
