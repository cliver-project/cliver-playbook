import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * Theme provider (ADR-0008): light / dark / system modes over the
 * `data-theme` attribute on <html>, persisted to localStorage
 * (key "cliver-theme" — keep in sync with the no-flash script in index.html).
 *
 * - `theme` is the user's choice ("system" allowed).
 * - `resolvedTheme` is what is actually applied ("light" | "dark") — use this
 *   when a component needs the concrete palette (e.g. the sonner Toaster).
 * - System mode reacts live to OS preference changes.
 */
export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "cliver-theme";

interface ThemeContextValue {
  theme: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(mode: ThemeMode): ResolvedTheme {
  const resolved: ResolvedTheme =
    mode === "system" ? (systemPrefersDark() ? "dark" : "light") : mode;
  document.documentElement.dataset.theme = resolved;
  return resolved;
}

function readStoredTheme(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(readStoredTheme);
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() =>
    // The no-flash script already set data-theme; trust it on first render.
    (document.documentElement.dataset.theme as ResolvedTheme) === "dark" ? "dark" : "light",
  );

  const setTheme = useCallback((mode: ThemeMode) => {
    setThemeState(mode);
    localStorage.setItem(STORAGE_KEY, mode);
    setResolvedTheme(applyTheme(mode));
  }, []);

  useEffect(() => {
    // React to OS preference flips while in system mode. Initial application
    // happens in the no-flash script (index.html) and on every setTheme call;
    // this effect only keeps system mode live.
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => setResolvedTheme(applyTheme("system"));
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [theme]);

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within <ThemeProvider>");
  }
  return ctx;
}
