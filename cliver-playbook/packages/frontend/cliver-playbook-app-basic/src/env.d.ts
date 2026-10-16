/**
 * Environment variables this package reads at build time.
 *
 * Declared here rather than relying on `vite/client` types: the package is
 * source-only and must type-check on its own, and this is the complete list of
 * variables it is allowed to depend on. The app may declare the same keys in
 * its own `vite-env.d.ts` — identical declarations merge.
 */
interface ImportMetaEnv {
  /**
   * Base URL for API calls. Empty (the default) means same-origin: the dev
   * server proxies `/api` to the backend, and a reverse proxy serves the SPA
   * and the API together in production. Set it when the API lives on another
   * origin (e.g. "https://api.example.com").
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
