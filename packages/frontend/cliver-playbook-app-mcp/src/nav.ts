import type { AuthedNavItem } from "cliver-playbook-app-user/layout/AuthAppLayout.tsx";

/**
 * The header entries this package adds to the app's navigation.
 *
 * Both are permission-gated, and the gate is the reason these live here rather
 * than in the app: the code that owns a page also declares which permission
 * makes it reachable. The layout filters the list against the viewer's
 * permissions, so an account without `mcp:*` never sees the entries — and the
 * server rejects the underlying calls regardless of what the header shows.
 */
export const mcpNavItems: AuthedNavItem[] = [
  { to: "/mcp/playground", labelKey: "nav.mcpPlayground", perm: "mcp:tools:invoke" },
  { to: "/mcp/agents", labelKey: "nav.mcpAgents", perm: "mcp:agents:read" },
];
