import { defineConfig } from "vite";

import { baseConfig } from "cliver-playbook-app-basic/tooling/vite.config.base.ts";

// Everything shared (React + Tailwind plugins, the /api dev proxy) comes from
// the package's base config; this shell adds nothing of its own.
export default defineConfig(baseConfig());
