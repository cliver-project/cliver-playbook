import type { RouteObject } from "react-router-dom";

import { RequirePerm } from "cliver-playbook-app-user/components/auth/RequirePerm.tsx";
import ChangePasswordPage from "cliver-playbook-app-user/pages/ChangePasswordPage.tsx";
import LoginPage from "cliver-playbook-app-user/pages/LoginPage.tsx";
import OAuthAuthorizePage from "cliver-playbook-app-user/pages/OAuthAuthorizePage.tsx";
import OAuthCallbackPage from "cliver-playbook-app-user/pages/OAuthCallbackPage.tsx";
import ProfilePage from "cliver-playbook-app-user/pages/ProfilePage.tsx";
import AuditPage from "cliver-playbook-app-user/pages/admin/AuditPage.tsx";
import OAuthPage from "cliver-playbook-app-user/pages/admin/OAuthPage.tsx";
import RolesPage from "cliver-playbook-app-user/pages/admin/RolesPage.tsx";
import UsersPage from "cliver-playbook-app-user/pages/admin/UsersPage.tsx";

/**
 * Routes rendered on their own, without the app chrome — the app spreads this
 * array at the top level of its route table.
 *
 * They are standalone by design: sign-in and the password gate happen before
 * the user is inside the app, the OIDC callback is a landing page whose whole
 * job is to hand a token back, and the OAuth 2.1 authorize page runs inside an
 * agent-initiated browser flow where app navigation would be actively
 * confusing. Their paths are absolute and deliberately listed in the same
 * place as the guard that matches them (`auth/session.ts`).
 */
export const userStandaloneRoutes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/change-password", element: <ChangePasswordPage /> },
  { path: "/auth/callback", element: <OAuthCallbackPage /> },
  { path: "/oauth/authorize", element: <OAuthAuthorizePage /> },
];

/**
 * Authenticated pages, rendered as children of the app's layout route
 * (`AuthAppLayout`), which is what provides the chrome and the coarse session
 * guard — hence the relative paths.
 *
 * Every admin page declares the permission its data needs through
 * `RequirePerm`; that is display gating only, since the server rejects
 * unauthorized calls regardless. The profile page is deliberately ungated:
 * every account owns exactly one profile.
 */
export const userRoutes: RouteObject[] = [
  { path: "profile", element: <ProfilePage /> },
  {
    path: "users",
    element: (
      <RequirePerm code="user:read">
        <UsersPage />
      </RequirePerm>
    ),
  },
  {
    path: "roles",
    element: (
      <RequirePerm code="role:read">
        <RolesPage />
      </RequirePerm>
    ),
  },
  {
    // Distinct from the standalone /oauth/authorize page above: this is the
    // admin view of the provider (registered clients, active grants).
    path: "oauth",
    element: (
      <RequirePerm code="oauth:read">
        <OAuthPage />
      </RequirePerm>
    ),
  },
  {
    path: "audit",
    element: (
      <RequirePerm code="audit:read">
        <AuditPage />
      </RequirePerm>
    ),
  },
];
