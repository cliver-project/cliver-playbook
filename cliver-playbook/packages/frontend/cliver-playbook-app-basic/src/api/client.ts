import axios from "axios";

/**
 * Shared HTTP client (ADR-0008: axios + interceptors, never hand-rolled fetch).
 *
 * - Base URL: empty by default (same-origin; the Vite dev proxy forwards /api
 *   to the backend). VITE_API_BASE_URL overrides for split deployments.
 * - Bearer injection: the auth layer registers a token getter via
 *   `setAuthTokenGetter` — this file stays free of auth state (the
 *   user-management template builds its AuthContext on this hook).
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
