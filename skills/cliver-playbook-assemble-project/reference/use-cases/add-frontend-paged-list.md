# Add a paged list page

## Use when

The backend returns the shared `Page<T>` envelope and the page needs a pager.
`usePagedQuery` owns the offset, keeps the previous page visible while the next
one loads, and steps back when the current window becomes empty.

Profile: any.

## Do

### 1. Type the API response

```ts
// src/api/orders.ts
import { api } from "cliver-playbook-app-basic/api/client.ts";
import type { Page } from "cliver-playbook-app-basic/api/pagination.ts";

export interface Order {
  id: number;
  status: string;
  total_cents: number;
}

export type OrderPage = Page<Order>;

export async function listOrders({
  status,
  limit,
  offset,
}: {
  status?: string;
  limit: number;
  offset: number;
}): Promise<OrderPage> {
  const { data } = await api.get<OrderPage>("/orders", {
    params: { status, limit, offset },
  });
  return data;
}
```

The backend must return `{ items, total, limit, offset }`. A bare array will
not work with the hook.

### 2. Use the hook

```tsx
import { usePagedQuery } from "cliver-playbook-app-basic/crud/usePagedQuery.ts";

const page = usePagedQuery({
  // Filter identity only. The hook appends { limit, offset } to the key.
  queryKey: ["orders", status],
  // A serialized filter change rewinds to page one before the query fires.
  resetKey: status,
  pageSize: 50,
  queryFn: ({ limit, offset }) => listOrders({ status, limit, offset }),
});
```

For multiple filters, serialize them deliberately:
`resetKey: \`${status}\u0000${ownerId}\``. Do not pass an object: identity
changes on every render would reset the offset.

### 3. Render the table and pager

```tsx
<DataTable
  columns={columns}
  rows={page.items}
  rowKey={(order) => order.id}
  isLoading={page.isLoading}
  emptyLabel={t("orders.empty")}
/>

<div className="flex items-center justify-end gap-3 text-sm">
  <span>
    {t("common.range", { from: page.from, to: page.to, total: page.total })}
  </span>
  <Button variant="outline" disabled={!page.canPrev} onClick={page.prevPage}>
    {t("common.previous")}
  </Button>
  <Button variant="outline" disabled={!page.canNext} onClick={page.nextPage}>
    {t("common.next")}
  </Button>
</div>
```

`from`/`to` are 1-based and `0..0` when the result set is empty. `isFetching`
can show a subtle loading state while the previous page remains visible.

### 4. Add the pager copy and test the behavior

Add `common.range`, `common.previous`, and `common.next` (or the project's
equivalents) to both locale bundles. Then check:

- Page 2 sends `offset=50`.
- Changing a filter sends `offset=0` on the first request, not a stale page.
- Deleting the last row on a page steps back instead of showing a blank table.
- A server 422 for an out-of-range window surfaces through `page.error`.

## Verify

```sh
pnpm typecheck
pnpm lint
pnpm build
```

Open the page and inspect the network requests: the query string carries
`limit` and `offset`, and the pager disables at the ends. A green build is not
proof of the reset behavior; exercise a filter change.

## Pitfalls

- **Do not put `limit`/`offset` in `queryKey`.** The hook owns them and appends
  the current window.
- **`resetKey` must be a stable serialization of the filters.** An object or a
  fresh array resets on every render.
- **`total` is the full filtered set, not `items.length`.** The pager depends
  on it.
- **Do not clamp locally.** The backend validates the window and returns 422;
  the hook does not hide a bad request.
- **Keep `pageSize` in sync with the backend's default.** A page size above
  the endpoint's `max_limit` is a 422.
- **The backend recipe comes first.** If the endpoint still returns a bare
  list, see `reference/use-cases/paginate-backend-endpoint.md`.

## Source of truth

- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/crud/usePagedQuery.ts`
  — `UsePagedQueryOptions`, `PagedQuery`.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/api/pagination.ts`
  — `Page<T>`, `PageRequest`.
- Worked example: `var/playbook/packages/frontend/cliver-playbook-app-user/src/pages/admin/AuditPage.tsx`.
- Deep dive: `packages/frontend/cliver-playbook-app-basic/README.md` section
  "Pagination".
