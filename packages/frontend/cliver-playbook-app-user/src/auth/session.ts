import axios from "axios";

import { api, setAuthTokenGetter } from "cliver-playbook-app-basic/api/client.ts";

/**
 * Session storage and client wiring (ADR-0008: the transport policy the server
 * enforces, mirrored where the UI can react to it).
 *
 * The HTTP client itself lives in the basic package and is deliberately
 * auth-agnostic — it only knows how to ask for a bearer token. This module is
 * the other half of that contract: where the token is kept, and what happens
 * when the server declares a session over.
 *
 * `installAuthClient()` must run once before the app renders, because axios
 * interceptors are global. It is idempotent, so an entry point can call it
 * unconditionally.
 */

/** localStorage key holding the session bearer token. */
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

/** Paths whose own auth flows must not be hijacked by the redirect logic. */
const AUTH_PAGE_PREFIXES = ["/login", "/change-password", "/auth/callback", "/oauth/authorize"];

function onAuthPage(): boolean {
  return AUTH_PAGE_PREFIXES.some(
    (prefix) =>
      window.location.pathname === prefix || window.location.pathname.startsWith(prefix + "/"),
  );
}

/**
 * Full-page navigation: deliberately not SPA routing — the interceptor runs
 * outside React, and a reload also drops every cached query result.
 */
function hardRedirect(path: string): void {
  if (!window.location.pathname.startsWith(path)) {
    window.location.assign(path);
  }
}

function isMustChangeDetail(detail: unknown): detail is { code: string } {
  return (
    typeof detail === "object" &&
    detail !== null &&
    (detail as { code?: unknown }).code === "must_change_password"
  );
}

let installed = false;

/**
 * Point the shared client at this session:
 *
 * - Bearer injection from localStorage, so every authenticated request carries
 *   the token without any call site passing it around.
 * - Response policy for the two ways a session ends early:
 *   - 401 — expired, revoked, or the user is gone. The token is dead
 *     regardless of which endpoint said so: clear it and reload to /login
 *     (the server is the authority).
 *   - 403 with `detail.code === "must_change_password"` — the account may do
 *     nothing else, so go to the gate page.
 *
 * Both redirects are suppressed on the pages that exist to handle auth errors
 * (login, change-password, callbacks) — otherwise a rejected sign-in attempt
 * would bounce the user away from the form.
 */
export function installAuthClient(): void {
  if (installed) return;
  installed = true;

  setAuthTokenGetter(getStoredToken);

  api.interceptors.response.use(
    (response) => response,
    (error) => {
      if (axios.isAxiosError(error) && error.response) {
        const { status, data } = error.response;
        if (status === 403 && isMustChangeDetail(data?.detail)) {
          if (!onAuthPage()) hardRedirect("/change-password");
        } else if (status === 401) {
          setStoredToken(null);
          if (!onAuthPage()) hardRedirect("/login");
        }
      }
      return Promise.reject(error);
    },
  );
}
