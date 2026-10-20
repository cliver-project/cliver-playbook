import { QueryClient } from "@tanstack/react-query";

/**
 * Shared TanStack Query client.
 *
 * - Stale time 30s: tables and detail views stop refetching on every mount
 *   while mutations still invalidate explicitly.
 * - Retry twice except for 4xx responses (client errors will not heal by
 *   replaying them).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        const status =
          typeof error === "object" && error !== null && "status" in error
            ? Number((error as { status: unknown }).status)
            : 0;
        if (status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});
