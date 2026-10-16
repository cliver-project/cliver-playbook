"""Item CRUD endpoints — the reference pattern for resource routers.

Layout convention: path params resolve the entity (404 when missing), request
bodies are validated Pydantic models, all persistence goes through the service
layer, and responses use the read schema.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate
from app.services import items as items_service

router = APIRouter(prefix="/api/v1/items", tags=["items"])


@router.get("", response_model=list[ItemRead])
async def list_items(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ItemRead]:
    items, _total = await items_service.list_items(db, limit=limit, offset=offset)
    return [ItemRead.model_validate(i) for i in items]


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate, db: AsyncSession = Depends(get_db)) -> ItemRead:
    item = await items_service.create_item(db, payload)
    return ItemRead.model_validate(item)


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(item_id: int, db: AsyncSession = Depends(get_db)) -> ItemRead:
    item = await items_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemRead.model_validate(item)


@router.patch("/{item_id}", response_model=ItemRead)
async def update_item(
    item_id: int, payload: ItemUpdate, db: AsyncSession = Depends(get_db)
) -> ItemRead:
    item = await items_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    updated = await items_service.update_item(db, item, payload)
    return ItemRead.model_validate(updated)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db)) -> None:
    item = await items_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    await items_service.delete_item(db, item)
