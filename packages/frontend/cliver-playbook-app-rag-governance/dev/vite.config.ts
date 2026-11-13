import { defineConfig } from "vite";

import { baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";

// Same shared config as every shell, with the `/api` proxy pointed at the
// standalone governance app instead of the composed dev backend (8000): this
// shell exists to drive the governance loop end to end (make gov-demo-up),
// and that app listens on 18000 (see the package README, "Local demo").
export default defineConfig(
  baseConfig({
    proxy: {
      "/api": { target: "http://127.0.0.1:18000", changeOrigin: true },
    },
  }),
);
