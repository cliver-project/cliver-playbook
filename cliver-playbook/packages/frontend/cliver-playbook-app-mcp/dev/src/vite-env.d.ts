/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL for API calls. Empty string (default) means same-origin — the
   * Vite dev proxy forwards /api to the backend. Set it when the frontend is
   * deployed on a different origin than the API (e.g. "https://api.example.com").
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
