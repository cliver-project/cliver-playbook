# Add a backend domain slice

## Use when

You need a product-owned table and its HTTP surface: model → migration →
service → schema → router → tests. This is the worked pattern from the
playbook's demo Items slice, applied under the project's own package.

Profile: `minimal`, `web`, `rag`, or `mcp`.

## Do

### 1. Register the permission codes first

For every profile except `minimal`, add the codes before the router module
imports. See `reference/use-cases/add-backend-permission-codes.md`.

### 2. Define the model on the project base

```python
# app/models/orders.py
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    total_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

Import the module in `app/models/__init__.py` so Alembic's `env.py` sees the
table. Do not add a database foreign key to `users` or another playbook table;
store the id as a plain indexed `BigInteger` and enforce existence in the
service layer (see the pitfall below).

### 3. Generate and review the migration

```sh
uv run alembic revision --autogenerate -m "orders"
uv run alembic upgrade head
```

Autogenerate is a draft. Review constraints, indexes, server defaults, and any
data backfill before committing. The project chain must apply to an empty
database and remain idempotent under `upgrade head`.

### 4. Add the schema and service

```python
# app/schemas/orders.py
from pydantic import BaseModel, ConfigDict


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: str
    total_cents: int
```

```python
# app/services/orders.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orders import Order


async def list_orders(db: AsyncSession, *, limit: int = 100) -> list[Order]:
    rows = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(min(limit, 500))
    )
    return list(rows.scalars())
```

Pick one transaction style and keep it: the service commits, or the router
commits once per request. Do not mix both in one path.

### 5. Add the router

```python
# app/api/orders.py
from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.orders import OrderRead
from app.services import orders as orders_service
from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

_READ = Security(require_perm("orders:read"))


@router.get("", response_model=list[OrderRead])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> list[OrderRead]:
    rows = await orders_service.list_orders(db)
    return [OrderRead.model_validate(row) for row in rows]
```

Add the router to `app/api/routes.py` (`ROUTERS = [orders_router]`) and import
that list in `create_app`. For the `minimal` profile, omit the
`Security`/`Viewer`/`require_perm` lines entirely; there is no identity
package and no permission dependency.

### 6. Test the real request path

Use the project test harness: a temp database, every migration chain in order,
an `admin_headers` fixture, and an `httpx.ASGITransport` client. Cover:

- unauthenticated → 401
- authenticated without the code → 403
- authorized → 200 with the expected shape

## Verify

```sh
uv run ruff check
uv run pytest tests/test_orders.py
uv run alembic upgrade head        # run twice: second run must be a no-op
```

Then fetch `/openapi.json` and confirm the route and response model appear.

## Pitfalls

- **Autogenerate cannot see an unimported model.** Import it from
  `app/models/__init__.py`.
- **Do not edit a playbook package's migration directory.** The project owns
  its own chain and version table.
- **A database FK to a playbook table scopes autogenerate to the playbook
  metadata.** Keep the id plain unless you deliberately share the playbook
  base and accept the tradeoff.
- **Import order:** `app.permissions` must run before the router module calls
  `require_perm(...)`.
- **A growing list belongs on the shared pagination contract.** See
  `reference/use-cases/paginate-backend-endpoint.md`.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/models/entities.py`
  — `Item`, the reference model.
- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/api/items.py`
  — the reference router.
- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/services/items.py`
  — the reference service.
- Deep dive: `reference/backend-composition.md` sections "Project migration
  chain" and "Domain slice".
