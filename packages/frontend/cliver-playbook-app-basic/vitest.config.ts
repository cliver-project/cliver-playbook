import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Package-level unit tests. Source-only packages are type-checked by the app
 * that consumes them; this harness keeps the reusable helpers honest without
 * building a full shell.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
  },
});
