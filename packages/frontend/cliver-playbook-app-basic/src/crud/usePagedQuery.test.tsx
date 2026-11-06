import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Page, PageRequest } from "../api/pagination.ts";
import { usePagedQuery } from "./usePagedQuery.ts";

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("usePagedQuery", () => {
  it("requests the first window and walks pages using the current total", async () => {
    const requests: PageRequest[] = [];
    const queryFn = vi.fn(async ({ limit, offset }: PageRequest): Promise<Page<string>> => {
      requests.push({ limit, offset });
      return {
        items: offset === 0 ? ["a", "b"] : ["c"],
        total: 51,
        limit,
        offset,
      };
    });

    const { result } = renderHook(
      () => usePagedQuery({ queryKey: ["rows"], queryFn, pageSize: 50 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.items).toEqual(["a", "b"]));
    expect(requests).toEqual([{ limit: 50, offset: 0 }]);
    expect(result.current).toMatchObject({
      offset: 0,
      total: 51,
      from: 1,
      to: 50,
      canPrev: false,
      canNext: true,
    });

    act(() => result.current.nextPage());

    await waitFor(() => expect(result.current.items).toEqual(["c"]));
    expect(requests).toEqual([
      { limit: 50, offset: 0 },
      { limit: 50, offset: 50 },
    ]);
    expect(result.current).toMatchObject({
      offset: 50,
      from: 51,
      to: 51,
      canPrev: true,
      canNext: false,
    });
  });

  it("rewinds to page one when resetKey changes", async () => {
    const requests: PageRequest[] = [];
    const queryFn = vi.fn(async ({ limit, offset }: PageRequest): Promise<Page<string>> => {
      requests.push({ limit, offset });
      return { items: [`row-${offset}`], total: 200, limit, offset };
    });

    const { result, rerender } = renderHook(
      ({ resetKey }: { resetKey: string }) =>
        usePagedQuery({ queryKey: ["rows", resetKey], queryFn, pageSize: 50, resetKey }),
      { initialProps: { resetKey: "all" }, wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.items).toEqual(["row-0"]));

    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.offset).toBe(50));

    rerender({ resetKey: "active" });
    expect(result.current.offset).toBe(0);

    await waitFor(() => expect(requests.at(-1)).toEqual({ limit: 50, offset: 0 }));
  });

  it("steps back a page when the current window became empty", async () => {
    const requests: PageRequest[] = [];
    const queryFn = vi.fn(async ({ limit, offset }: PageRequest): Promise<Page<string>> => {
      requests.push({ limit, offset });
      return {
        items: offset === 0 ? ["only"] : [],
        total: 1,
        limit,
        offset,
      };
    });

    const { result } = renderHook(
      () => usePagedQuery({ queryKey: ["rows"], queryFn, pageSize: 50 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.items).toEqual(["only"]));

    act(() => result.current.setOffset(50));

    await waitFor(() => expect(result.current.offset).toBe(0));
    expect(result.current.items).toEqual(["only"]);
    expect(requests).toContainEqual({ limit: 50, offset: 50 });
  });
});
