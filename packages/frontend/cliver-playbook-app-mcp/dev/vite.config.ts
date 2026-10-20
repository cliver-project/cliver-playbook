import { defineConfig } from "vite";

import {
  DEV_BACKEND,
  baseConfig,
} from "cliver-playbook-app-basic/tooling/vite.config.base.ts";

// The shared config brings the React and Tailwind plugins and the `/api` proxy.
// This shell adds the one path the MCP package needs: the MCP endpoint lives
// outside `/api` (the server owns its path shape) and the playground is a real
// MCP client — POSTing JSON-RPC and reading SSE responses — so the dev server
// has to forward it too. Keep the path in sync with the backend's `mcp.mount_path`.
export default defineConfig(
  baseConfig({ proxy: { "/mcp": { target: DEV_BACKEND, changeOrigin: true } } }),
);
