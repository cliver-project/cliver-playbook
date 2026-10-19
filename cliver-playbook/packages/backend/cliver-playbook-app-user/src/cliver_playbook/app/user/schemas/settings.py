"""Schemas for the admin runtime-settings surface (ADR-0021).

The shape is deliberately generic: a section describes its own fields, and
the API returns those descriptions unchanged. Adding a setting is a change
to the owning package's ``settings_section`` module, never to this file.
A secret never carries a value — only ``configured`` tells the UI whether one
is available. Secrets are write-only: the UI may submit a replacement, which
is persisted with the section, unless the environment manages the field.
"""

from typing import Any

from pydantic import BaseModel, Field


class SettingsFieldRead(BaseModel):
    """One editable value, described by the package that owns it."""

    name: str
    label: str
    type: str
    description: str
    enum: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    env_var: str | None = None
    secret: bool = False
    # Optional presentation grouping: fields sharing a key render together
    # under one heading. ``group_title`` is the owner's untranslated label.
    # ``subgroup`` nests a second heading inside the group.
    group: str | None = None
    group_title: str = ""
    subgroup: str | None = None
    subgroup_title: str = ""
    # True when the environment (or .env) manages the field: the UI renders
    # the value read-only and the server rejects writes. A secret without an
    # environment value is writable but never returns its value.
    read_only: bool = False
    # "environment" | "runtime" | "config" — where the effective value comes
    # from, so the operator understands what a reset would do.
    source: str
    value: Any = None
    configured: bool | None = None


class SettingsSectionRead(BaseModel):
    key: str
    title: str
    description: str
    fields: list[SettingsFieldRead]


class SettingsUpdate(BaseModel):
    """A partial section update; unspecified fields keep their current value."""

    values: dict[str, Any] = Field(default_factory=dict)
