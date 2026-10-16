import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/components/auth/AuthContext";
import { RequirePerm } from "@/components/auth/RequirePerm";
import { ThemeProvider } from "@/components/theme/ThemeProvider";
import { Toaster } from "@/components/ui/sonner";
import AppLayout from "@/layouts/AppLayout";
import { queryClient } from "@/lib/queryClient";
import ChangePasswordPage from "@/pages/ChangePasswordPage";
import HomePage from "@/pages/HomePage";
import ItemsPage from "@/pages/ItemsPage";
import LoginPage from "@/pages/LoginPage";
import MCPPlaygroundPage from "@/pages/MCPPlaygroundPage";
import OAuthAuthorizePage from "@/pages/OAuthAuthorizePage";
import OAuthCallbackPage from "@/pages/OAuthCallbackPage";
import ProfilePage from "@/pages/ProfilePage";
import AuditPage from "@/pages/admin/AuditPage";
import MCPAgentsPage from "@/pages/admin/MCPAgentsPage";
import OAuthPage from "@/pages/admin/OAuthPage";
import RolesPage from "@/pages/admin/RolesPage";
import UsersPage from "@/pages/admin/UsersPage";

/**
 * Application shell: providers (query cache -> theme -> router -> session)
 * plus the route table.
 *
 * Route groups:
 * - Standalone auth pages (no app chrome): login, change-password, the OIDC
 *   callback landing page, and the OAuth 2.1 agent authorize page — the last
 *   renders inside an agent-initiated browser flow, so app navigation would
 *   be actively confusing there.
 * - Chrome + guarded pages: AppLayout redirects anonymous visitors to /login
 *   and must-change-password accounts to /change-password; each admin page
 *   additionally declares the permission it needs via RequirePerm (display
 *   gating — the server enforces regardless).
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/change-password" element={<ChangePasswordPage />} />
              <Route path="/auth/callback" element={<OAuthCallbackPage />} />
              <Route path="/oauth/authorize" element={<OAuthAuthorizePage />} />

              <Route element={<AppLayout />}>
                <Route index element={<HomePage />} />
                <Route path="items" element={<ItemsPage />} />
                {/* Every authenticated user owns their profile — no permission gate. */}
                <Route path="profile" element={<ProfilePage />} />
                <Route
                  path="users"
                  element={
                    <RequirePerm code="user:read">
                      <UsersPage />
                    </RequirePerm>
                  }
                />
                <Route
                  path="roles"
                  element={
                    <RequirePerm code="role:read">
                      <RolesPage />
                    </RequirePerm>
                  }
                />
                {/* Distinct from the standalone /oauth/authorize page above:
                    this is the ADMIN view of the provider (clients, grants). */}
                <Route
                  path="oauth"
                  element={
                    <RequirePerm code="oauth:read">
                      <OAuthPage />
                    </RequirePerm>
                  }
                />
                <Route
                  path="audit"
                  element={
                    <RequirePerm code="audit:read">
                      <AuditPage />
                    </RequirePerm>
                  }
                />
                {/* MCP surface. The playground invokes tools
                    (mcp:tools:invoke); the agents view reads MCP activity
                    without needing the full identity audit trail
                    (mcp:agents:read) — both enforced server-side too. */}
                <Route
                  path="mcp/playground"
                  element={
                    <RequirePerm code="mcp:tools:invoke">
                      <MCPPlaygroundPage />
                    </RequirePerm>
                  }
                />
                <Route
                  path="mcp/agents"
                  element={
                    <RequirePerm code="mcp:agents:read">
                      <MCPAgentsPage />
                    </RequirePerm>
                  }
                />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            <Toaster />
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
