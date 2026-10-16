// A path reference is the only mechanism that works here: the file it names
// declares globals (augmentations), and an augmentation cannot be reached by
// an `import` — which is what the rule below assumes. Without it, any program
// that compiles this file (a consuming package's own typecheck) would report
// `import.meta.env` as an unknown property, since a source-only package's
// ambient declarations do not travel through the consumer's `include`.
// oxlint-disable-next-line typescript/triple-slash-reference
/// <reference path="../env.d.ts" />
import axios from "axios";

/**
 * Shared HTTP client (ADR-0008: axios + interceptors, never hand-rolled fetch).
 *
 * - Base URL: empty by default (same-origin; the Vite dev proxy forwards /api
 *   to the backend). VITE_API_BASE_URL overrides for split deployments.
 * - Bearer injection: the auth layer registers a token getter via
 *   `setAuthTokenGetter` — this file stays free of auth state (the user
 *   package's `auth/session.ts` is the implementation of that hook).
 */
export const api = axios.create({
  baseURL: (import.meta.env.VITE_API_BASE_URL ?? "") + "/api/v1",
});

type TokenGetter = () => string | null;

let tokenGetter: TokenGetter = () => null;

/** Register the bearer-token source; call with `null`-returning fn to clear. */
export function setAuthTokenGetter(getter: TokenGetter): void {
  tokenGetter = getter;
}

api.interceptors.request.use((config) => {
  const token = tokenGetter();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** Extract a human-readable message from an axios error payload. */
export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
    return error.message;
  }
  return String(error);
}
