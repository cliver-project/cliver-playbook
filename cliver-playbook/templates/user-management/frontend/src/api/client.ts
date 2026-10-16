import axios from "axios";

/**
 * Shared HTTP client (ADR-0008: axios + interceptors, never hand-rolled fetch).
 *
 * - Base URL: empty by default (same-origin; the Vite dev proxy forwards /api
 *   to the backend). VITE_API_BASE_URL overrides for split deployments.
 * - Bearer injection: reads the stored session token by default; override the
 *   source with `setAuthTokenGetter` (tests, embedded flows).
 * - Response interceptors (user-management additions, mirroring the server's
 *   enforcement so the UI reacts to session death instead of silently
 *   failing):
 *     - 401 -> clear the stored token, full reload to /login (the server is
 *       the authority; the token is gone for good).
 *     - 403 with detail.code === "must_change_password" -> redirect to
 *       /change-password (server gate: the account may do nothing else).
 *   Both redirects are suppressed on pages that exist to handle auth errors
 *   (login, change-password, callbacks) to avoid redirect loops.
 */

/** localStorage key for the session bearer token. */
export const TOKEN_STORAGE_KEY = "cliver-token";

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null; // storage unavailable (private mode etc.) — behave logged out
  }
}

/** Store the session token; pass null to clear (logout, session death). */
export function setStoredToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(TOKEN_STORAGE_KEY);
    else localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Storage unavailable — the in-flight request just goes out anonymous.
  }
}

export const api = axios.create({
  baseURL: (import.meta.env.VITE_API_BASE_URL ?? "") + "/api/v1",
});

type TokenGetter = () => string | null;

let tokenGetter: TokenGetter = getStoredToken;

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

/** Pages whose own auth flows must not be hijacked by the redirect logic. */
const AUTH_PAGE_PREFIXES = ["/login", "/change-password", "/auth/callback", "/oauth/authorize"];

function onAuthPage(): boolean {
  return AUTH_PAGE_PREFIXES.some(
    (prefix) => window.location.pathname === prefix || window.location.pathname.startsWith(prefix + "/"),
  );
}

/** Full-page navigation: deliberately not SPA routing — the interceptor runs
 * outside React, and a reload also drops every cached query result. */
function hardRedirect(path: string): void {
  if (!window.location.pathname.startsWith(path)) {
    window.location.assign(path);
  }
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response) {
      const { status, data } = error.response;
      const detail: unknown = data?.detail;
      if (status === 403 && isMustChangeDetail(detail)) {
        if (!onAuthPage()) hardRedirect("/change-password");
      } else if (status === 401) {
        // Session revoked/expired/deleted user. The token is dead regardless
        // of which endpoint said so.
        setStoredToken(null);
        if (!onAuthPage()) hardRedirect("/login");
      }
    }
    return Promise.reject(error);
  },
);

function isMustChangeDetail(detail: unknown): detail is { code: string } {
  return (
    typeof detail === "object" &&
    detail !== null &&
    (detail as { code?: unknown }).code === "must_change_password"
  );
}

/** Extract a human-readable message from an axios error payload. */
export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
    return error.message;
  }
  return String(error);
}
