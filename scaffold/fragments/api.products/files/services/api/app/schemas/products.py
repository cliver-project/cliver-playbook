"""Product request/response contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    price_cents: int = Field(default=0, ge=0)


class ProductCreate(ProductBase):
    """Payload for POST /api/v1/products."""


class ProductUpdate(BaseModel):
    """Payload for PATCH /api/v1/products/{id}; all fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    price_cents: int | None = Field(default=None, ge=0)


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
