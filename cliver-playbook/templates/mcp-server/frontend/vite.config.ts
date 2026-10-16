import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // Same-origin development: the SPA calls /api/* and Vite forwards to the
      // FastAPI backend. Production deployments set VITE_API_BASE_URL instead.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      // The MCP endpoint lives OUTSIDE /api (the SDK owns its path shape;
      // default is settings.mcp.mount_path = /mcp) and the playground page is
      // a real MCP client — POSTing JSON-RPC with SSE responses — so the dev
      // proxy must forward it too. Keep in sync if mcp.mount_path changes.
      "/mcp": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
