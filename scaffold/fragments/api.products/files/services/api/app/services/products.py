"""Product persistence; routers own HTTP concerns."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.products import Product
from app.schemas.products import ProductCreate, ProductUpdate


async def list_products(
    db: AsyncSession, *, limit: int = 50, offset: int = 0
) -> tuple[list[Product], int]:
    rows = await db.execute(
        select(Product)
        .order_by(Product.created_at.desc(), Product.id.desc())
        .limit(limit)
        .offset(offset)
    )
    total = await db.scalar(select(func.count()).select_from(Product))
    return list(rows.scalars().all()), int(total or 0)


async def get_product(db: AsyncSession, product_id: int) -> Product | None:
    return await db.get(Product, product_id)


async def create_product(db: AsyncSession, payload: ProductCreate) -> Product:
    product = Product(**payload.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def update_product(db: AsyncSession, product: Product, payload: ProductUpdate) -> Product:
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(product, field, value)
    if changes:
        await db.commit()
        await db.refresh(product)
    return product


async def delete_product(db: AsyncSession, product: Product) -> None:
    await db.delete(product)
    await db.commit()
