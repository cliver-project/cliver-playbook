import { defineConfig } from "vite";

import { baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";

// The shared config brings the React and Tailwind plugins and the `/api`
// proxy. The RAG endpoints all live under `/api/v1/rag`, so this shell needs
// nothing beyond it — unlike the mcp shell, which also forwards `/mcp`.
export default defineConfig(baseConfig());
