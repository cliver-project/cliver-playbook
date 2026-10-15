"""Item CRUD service.

Functions take an `AsyncSession` and stay transport-agnostic: routers own
HTTP concerns, services own persistence rules. This layer is the seam a
future template (or a real domain) extends.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Item
from app.schemas.item import ItemCreate, ItemUpdate


async def list_items(
    db: AsyncSession, *, limit: int = 50, offset: int = 0
) -> tuple[list[Item], int]:
    """Return (items, total_count) ordered by newest first."""
    rows = await db.execute(
        select(Item).order_by(Item.created_at.desc(), Item.id.desc()).limit(limit).offset(offset)
    )
    total = await db.scalar(select(func.count()).select_from(Item))
    return list(rows.scalars().all()), int(total or 0)


async def get_item(db: AsyncSession, item_id: int) -> Item | None:
    return await db.get(Item, item_id)


async def create_item(db: AsyncSession, payload: ItemCreate) -> Item:
    item = Item(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_item(db: AsyncSession, item: Item, payload: ItemUpdate) -> Item:
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(item, field, value)
    if changes:
        await db.commit()
        await db.refresh(item)
    return item


async def delete_item(db: AsyncSession, item: Item) -> None:
    await db.delete(item)
    await db.commit()
