# Add an entity CRUD page

## Use when

The project needs the standard "table of things with create/edit/delete"
surface. Use the shared `useCrudQueries` and `DataTable` instead of writing
query invalidation, toasts, and table states again.

Profile: any.

## Do

### 1. Write a typed API module

```ts
// src/api/orders.ts
import { api } from "cliver-playbook-app-basic/api/client.ts";

export interface Order {
  id: number;
  status: string;
  total_cents: number;
}

export interface OrderCreateInput {
  status: string;
  total_cents: number;
}

export type OrderUpdateInput = Partial<OrderCreateInput>;

export async function listOrders(): Promise<Order[]> {
  const { data } = await api.get<Order[]>("/orders");
  return data;
}

export async function createOrder(input: OrderCreateInput): Promise<Order> {
  const { data } = await api.post<Order>("/orders", input);
  return data;
}

export async function updateOrder(id: number, input: OrderUpdateInput): Promise<Order> {
  const { data } = await api.patch<Order>(`/orders/${id}`, input);
  return data;
}

export async function deleteOrder(id: number): Promise<void> {
  await api.delete(`/orders/${id}`);
}
```

Use the shared `api` instance. Do not create a second axios client; the auth
interceptors are installed on this one.

### 2. Copy the page shape, not the implementation

`var/playbook/packages/frontend/cliver-playbook-app-basic/src/pages/ItemsPage.tsx`
is the worked example. Keep the API module, form fields, columns, and i18n
keys; replace everything entity-specific. The shared plumbing is:

```tsx
const crud = useCrudQueries<Order, OrderCreateInput, OrderUpdateInput>({
  queryKey: ["orders"],
  list: listOrders,
  create: createOrder,
  update: updateOrder,
  remove: deleteOrder,
  messages: {
    created: t("orders.created"),
    updated: t("orders.updated"),
    deleted: t("orders.deleted"),
  },
  onSuccess: () => setDialog(null),
});
```

`useCrudQueries` owns the list query, create/update/delete mutations,
invalidation of `queryKey`, success toasts, and error toasts. The page owns the
form and dialog.

### 3. Render the table

```tsx
<DataTable
  columns={columns}
  rows={crud.items.data}
  rowKey={(order) => order.id}
  isLoading={crud.items.isLoading}
  emptyLabel={t("orders.empty")}
/>
```

`DataTableColumn<T>` is `{ key, header, render, className? }`. Any cell
content is a render function; do not extend the table with a config DSL.

### 4. Route and translate

Add the page with `reference/use-cases/add-frontend-page.md`. Add the
`orders.*` keys and `nav.orders` to both locale bundles.

## Verify

```sh
pnpm typecheck
pnpm lint
pnpm build
```

Create a row, edit it, delete it, and confirm the table refreshes without a
manual reload. Then trigger a server error and confirm the toast shows the
API message and the dialog stays open.

## Pitfalls

- **One query key per entity list.** The mutations invalidate exactly that key;
  a typo leaves stale rows on screen.
- **Do not duplicate mutation state in the page.** `crud.create.isPending`,
  `crud.update.isPending`, and `crud.remove.isPending` are the pending flags.
- **Do not close a dialog before the mutation resolves.** Close it in
  `onSuccess`; a failure keeps the form and the user's input.
- **The API id is numeric in the shared pattern.** If the domain uses string
  ids, adapt the API module and the mutation wrapper together; do not cast at
  the call site.
- **A read-only entity simply omits the unused mutation and action column.**
  Do not invent a second generic hook.

## Source of truth

- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/crud/useCrudQueries.ts`
  — `CrudConfig`, `useCrudQueries`.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/crud/DataTable.tsx`
  — `DataTable`, `DataTableColumn`.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/pages/ItemsPage.tsx`
  — the full worked page.
- `var/playbook/packages/frontend/cliver-playbook-app-basic/src/api/items.ts`
  — the reference API module.
