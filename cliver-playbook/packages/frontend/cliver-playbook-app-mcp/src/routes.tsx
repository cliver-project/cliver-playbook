import type { RouteObject } from "react-router-dom";

import MCPPlaygroundPage from "cliver-playbook-app-mcp/pages/MCPPlaygroundPage.tsx";
import MCPAgentsPage from "cliver-playbook-app-mcp/pages/admin/MCPAgentsPage.tsx";
import { RequirePerm } from "cliver-playbook-app-user/components/auth/RequirePerm.tsx";

/**
 * The pages this package contributes, as children of the app's layout route
 * (`AuthAppLayout`) — hence the relative paths, the chrome and the session
 * guard both come from there.
 *
 * Each page declares the permission its data needs through `RequirePerm`. That
 * is display gating only: the server rejects an unauthorized call whatever the
 * browser renders, and the playground reaches the MCP endpoint as the signed-in
 * user, so its own session token is what the gate on the other side checks.
 */
export const mcpRoutes: RouteObject[] = [
  {
    path: "mcp/playground",
    element: (
      <RequirePerm code="mcp:tools:invoke">
        <MCPPlaygroundPage />
      </RequirePerm>
    ),
  },
  {
    path: "mcp/agents",
    element: (
      <RequirePerm code="mcp:agents:read">
        <MCPAgentsPage />
      </RequirePerm>
    ),
  },
];
