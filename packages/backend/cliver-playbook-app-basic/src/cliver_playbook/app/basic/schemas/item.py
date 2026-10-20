"""Pydantic schemas for the Item demo entity (request/response contracts)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    quantity: int = Field(default=0, ge=0)


class ItemCreate(ItemBase):
    """Payload for POST /api/v1/items."""


class ItemUpdate(BaseModel):
    """Payload for PATCH /api/v1/items/{id} — all fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    quantity: int | None = Field(default=None, ge=0)


class ItemRead(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
