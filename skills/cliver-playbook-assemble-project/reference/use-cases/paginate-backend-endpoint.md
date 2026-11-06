# Paginate a backend endpoint

## Use when

A list endpoint can grow beyond one screen or one response. Use the shared
`Page[T]` envelope and `page_params()` instead of inventing `limit`/`offset`
per route.

Profile: any.

## Do

### 1. Parse the window with the shared dependency

```python
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.api.pagination import PageParams, page_params
from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.basic.schemas.pagination import Page

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.get("", response_model=Page[OrderRead])
async def list_orders(
    params: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
    db: AsyncSession = Depends(get_db),
) -> Page[OrderRead]:
    rows = (
        (
            await db.execute(
                select(Order)
                .order_by(Order.updated_at.desc(), Order.id.desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        )
        .scalars()
        .all()
    )
    total = await db.scalar(select(func.count()).select_from(Order))
    return Page[OrderRead](
        items=[OrderRead.model_validate(row) for row in rows],
        total=int(total or 0),
        limit=params.limit,
        offset=params.offset,
    )
```

Apply the **same filters** to the rows query and the count query. `total` is
the size of the full filtered set, not `len(items)`.

### 2. Choose the bounds per endpoint

`page_params(default_limit=50, max_limit=200)` validates both at import time.
A feed that serves more rows can use different bounds; do not silently clamp a
request. An out-of-range `limit` or `offset` is a 422.

### 3. Index the order

Offset pagination is only stable when the `ORDER BY` is deterministic. Add a
matching index in the project migration, for example
`(user_id, updated_at)` for a per-user feed or `(updated_at, id)`. Always add a
tiebreaker column (`id`) when timestamps can collide.

### 4. Test the contract

```python
async def test_orders_page(client, admin_headers):
    response = await client.get("/api/v1/orders", headers=admin_headers)
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["limit"] == 50
    assert body["offset"] == 0

    limited = await client.get(
        "/api/v1/orders?limit=1&offset=1", headers=admin_headers
    )
    assert len(limited.json()["items"]) <= 1
    assert limited.json()["offset"] == 1

    assert (await client.get("/api/v1/orders?limit=0", headers=admin_headers)).status_code == 422
```

## Verify

```sh
uv run pytest tests/test_orders.py -k pag
uv run ruff check
```

Fetch the endpoint and confirm `total` stays constant while `offset` changes,
and that `limit`/`offset` echo the applied window.

## Pitfalls

- **Do not return a bare list** from a new list endpoint that the frontend
  types as `Page<T>`; the client pager reads all four fields.
- **Do not omit the count** or count only `items`: "next page" becomes
  undecidable.
- **Offset pagination shifts under concurrent inserts/deletes.** That is
  acceptable for admin and activity surfaces; a high-churn feed that needs
  stable pages should use keyset pagination behind the same envelope later.
- **A filter change must reset the offset** on the client. The frontend recipe
  passes a serialized `resetKey` to `usePagedQuery`.
- **The response shape is additive.** Existing clients that ignore
  `limit`/`offset` keep working; clients that expect a bare array do not.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/schemas/pagination.py`
  — `Page[T]`.
- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/api/pagination.py`
  — `PageParams`, `page_params`.
- Worked examples: the user package's `/api/v1/admin/audit` and the MCP
  package's activity feed.
- Deep dive: `packages/backend/cliver-playbook-app-basic/README.md` section
  "Pagination".
- Frontend: `reference/use-cases/add-frontend-paged-list.md`.
