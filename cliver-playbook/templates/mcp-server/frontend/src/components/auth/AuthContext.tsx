import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { CurrentUser } from "@/api/auth";
import { fetchMe, login as apiLogin, logout as apiLogout } from "@/api/auth";
import { getStoredToken, setStoredToken } from "@/api/client";

/**
 * Session state for the whole SPA.
 *
 * Deliberately tiny (~no network logic beyond /me): token transport lives in
 * api/client.ts, server-state caching lives in TanStack Query. This context
 * answers three questions: who is logged in, can the UI show a given
 * affordance, and how do we log in/out.
 *
 * The token itself lives in localStorage under a fixed key — surviving reload
 * — and every authenticated request picks it up through the axios interceptor.
 */

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUser | null;
  /** Password login: stores the token and adopts the returned profile. */
  login: (username: string, password: string) => Promise<CurrentUser>;
  /** Adopt a token issued outside the login form (OIDC callback fragment):
   * stores it, then resolves the profile — or null if the token is no good. */
  adoptToken: (token: string) => Promise<CurrentUser | null>;
  /** Revoke the current session server-side; always clears local state. */
  logout: () => Promise<void>;
  /** Refresh the profile (e.g. after a password change re-issue). */
  refresh: () => Promise<void>;
  /** Display-only permission check — the server enforces regardless. */
  hasPerm: (code: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);

  // On mount: a stored token is adopted only if /me still accepts it. Any 401
  // here is handled by the axios interceptor (clear + redirect to /login) —
  // this effect just converges to "anonymous" so the router renders.
  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      if (!getStoredToken()) {
        setStatus("anonymous");
        return;
      }
      try {
        const me = await fetchMe();
        if (!cancelled) {
          setUser(me);
          setStatus("authenticated");
        }
      } catch {
        if (!cancelled) setStatus("anonymous");
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await apiLogin(username, password);
    setStoredToken(result.token);
    setUser(result.user);
    setStatus("authenticated");
    return result.user;
  }, []);

  const adoptToken = useCallback(async (token: string) => {
    setStoredToken(token);
    try {
      const me = await fetchMe();
      setUser(me);
      setStatus("authenticated");
      return me;
    } catch {
      // Token already rejected: fall back to anonymous; the interceptor has
      // already cleared storage on the 401.
      setStatus("anonymous");
      return null;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Best effort: even if the network call fails, local state must go.
    }
    setStoredToken(null);
    setUser(null);
    setStatus("anonymous");
  }, []);

  const refresh = useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
  }, []);

  const hasPerm = useCallback(
    (code: string) => Boolean(user?.permissions.includes(code)),
    [user],
  );

  const value = useMemo(
    () => ({ status, user, login, adoptToken, logout, refresh, hasPerm }),
    [status, user, login, adoptToken, logout, refresh, hasPerm],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
