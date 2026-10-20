/**
 * Public surface of the mcp frontend package.
 *
 * Two import styles, the same as the packages this one sits on: the barrel for
 * the handful of things an app wires up once (routes, nav entries, locales),
 * deep paths (`cliver-playbook-app-mcp/api/mcp.ts`) for everything else. Deep
 * paths carry the source extension — the package's `exports` patterns are
 * matched exactly, which is what makes one package resolvable from another with
 * no aliases configured in the consuming app.
 */

export {
  callMcpTool,
  fetchMcpInfo,
  listMcpCalls,
  listMcpTools,
  mcpEndpointUrl,
  type McpCallDetail,
  type McpCallPage,
  type McpCallRow,
  type McpInfo,
  type McpToolDef,
  type McpToolResult,
} from "cliver-playbook-app-mcp/api/mcp.ts";
export { mcpTranslations } from "cliver-playbook-app-mcp/locales/index.ts";
export { mcpNavItems } from "cliver-playbook-app-mcp/nav.ts";
export { mcpRoutes } from "cliver-playbook-app-mcp/routes.tsx";
