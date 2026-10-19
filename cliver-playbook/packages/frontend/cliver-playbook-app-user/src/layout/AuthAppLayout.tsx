import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "cliver-playbook-app-basic/components/ui/dropdown-menu.tsx";
import {
  AppLayout,
  basicNavItems,
  type NavItem,
} from "cliver-playbook-app-basic/layout/AppLayout.tsx";
import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";

/** A navigation entry that is only shown to viewers holding `perm`. */
export interface AuthedNavItem extends NavItem {
  /** Permission code required to see the entry; null = always visible. */
  perm: string | null;
}

/** This package's authenticated pages — the navigation of a user-management app. */
export const userNavItems: AuthedNavItem[] = [
  { to: "/users", labelKey: "nav.users", perm: "user:read" },
  { to: "/roles", labelKey: "nav.roles", perm: "role:read" },
  { to: "/oauth", labelKey: "nav.oauth", perm: "oauth:read" },
  { to: "/settings", labelKey: "nav.settings", perm: "settings:read" },
  { to: "/audit", labelKey: "nav.audit", perm: "audit:read" },
];

export interface AuthAppLayoutProps {
  /**
   * Navigation entries contributed by other packages, so a composed app keeps
   * one header (R6: the MCP package's pages).
   */
  extraNavItems?: AuthedNavItem[];
  /** Extra header controls, rendered beside the language/theme switchers. */
  headerExtra?: ReactNode;
}

/**
 * The app's layout route for a user-management app: the basic `AppLayout`
 * chrome plus everything that is only true when there is a session.
 *
 * It is also the SPA's coarse auth guard — the counterpart of the server's
 * bearer dependency: while the session boots it shows a calm placeholder,
 * anonymous visitors are bounced to /login (with a return path), and accounts
 * the server flagged must_change_password are steered to the gate page. The
 * per-page permission gates (`RequirePerm`) sit on top of this; the server
 * enforces regardless of both.
 *
 * Header entries are merged here rather than passed in, because the set of
 * visible entries depends on the viewer's permissions, which only this package
 * knows::
 *
 *     { element: <AuthAppLayout />, children: [...basicRoutes, ...userRoutes] }
 */
export function AuthAppLayout({ extraNavItems = [], headerExtra }: AuthAppLayoutProps) {
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

  const navItems: NavItem[] = [
    ...basicNavItems,
    ...[...userNavItems, ...extraNavItems].filter(
      (item) => item.perm === null || hasPerm(item.perm),
    ),
  ];

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <AppLayout
      navItems={navItems}
      headerExtra={
        <>
          {headerExtra}
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
        </>
      }
    />
  );
}

export default AuthAppLayout;
