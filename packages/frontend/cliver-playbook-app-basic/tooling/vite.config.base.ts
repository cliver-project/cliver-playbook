import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { ProxyOptions, UserConfig } from "vite";

/**
 * Shared Vite configuration for apps that consume these packages.
 *
 * Plugins and the dev-server proxy are the same in every app built on the
 * library; a package that adds backend routes (the MCP endpoint, the OAuth
 * discovery documents) extends `proxy` instead of writing its own config::
 *
 *     import { baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";
 *     export default defineConfig(baseConfig({ proxy: { "/mcp": { … } } }));
 *
 * Same-origin by default: the SPA calls `/api/*` and Vite forwards to the
 * backend, so no CORS setup is needed in development. A split deployment sets
 * `VITE_API_BASE_URL` instead (see `api/client.ts`).
 *
 * Deep package imports carry the file extension (`…/tooling/vite.config.base.ts`)
 * because `exports` subpath patterns are matched exactly — see the README.
 */

/**
 * Where the FastAPI backend listens in development. Exported so an app that
 * proxies an extra path (the MCP endpoint) still names the backend once.
 */
export const DEV_BACKEND = "http://127.0.0.1:8000";

export interface BaseViteOptions {
  /** Extra proxy entries, merged over the `/api` default. */
  proxy?: Record<string, ProxyOptions>;
}

export function baseConfig(options: BaseViteOptions = {}): UserConfig {
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": { target: DEV_BACKEND, changeOrigin: true },
        ...options.proxy,
      },
    },
  };
}
