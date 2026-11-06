import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { lazyRoute } from "./routes.tsx";

function LoadedPage(_props: Record<string, never>) {
  return <div>Loaded page</div>;
}

describe("lazyRoute", () => {
  it("builds the index route and shows the fallback until the page loads", async () => {
    const route = lazyRoute(() => Promise.resolve({ default: LoadedPage }), {
      index: true,
      fallback: <div>Loading index</div>,
    });

    expect(route.index).toBe(true);
    expect(route.path).toBeUndefined();

    render(route.element as ReactElement);
    expect(screen.getByText("Loading index")).toBeTruthy();
    expect(await screen.findByText("Loaded page")).toBeTruthy();
  });

  it("builds a path route and applies the wrapper before requesting the page", async () => {
    let resolveModule!: (module: { default: typeof LoadedPage }) => void;
    const load = vi.fn(
      () =>
        new Promise<{ default: typeof LoadedPage }>((resolve) => {
          resolveModule = resolve;
        }),
    );

    const route = lazyRoute(load, {
      path: "orders",
      fallback: <div>Loading orders</div>,
      wrap: (page) => <section aria-label="permission gate">{page}</section>,
    });

    expect(route.index).toBeUndefined();
    expect(route.path).toBe("orders");

    render(route.element as ReactElement);
    expect(screen.getByLabelText("permission gate")).toBeTruthy();
    expect(screen.getByText("Loading orders")).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveModule({ default: LoadedPage });
    });

    expect(screen.getByText("Loaded page")).toBeTruthy();
  });
});
