"""Module-owned runtime settings: registry, validation, persistence, overlay.

ADR-0021. Configuration has four layers, highest precedence first:

    environment > .env > persisted runtime overrides > app.yaml > defaults

The first two and ``app.yaml`` are resolved by pydantic-settings when the
process starts; this module owns the middle layer. A package registers a
``SettingsSection`` at import time — its fields, labels, allowed values, and
the functions that read/apply the section on a Settings instance. The central
admin API (in the identity package) never interprets those fields itself; it
asks each section to describe itself, validates the request, and calls the
owner's ``apply``. That is how RAG settings stay owned by RAG while the
administrator sees one settings surface.

Boundaries (deliberate, see the ADR):

- Environment-managed fields are read-only. An explicit ``env_var`` is checked
  against the process environment and the project ``.env``; a persisted
  override for such a field is ignored on load and rejected on write, because
  the environment would win at the next restart anyway.
- Secrets are write-only. The API accepts a new value, persists it with the
  section, and never returns it — the description reports only configured /
  not configured. An environment variable or ``.env`` entry with the declared
  ``env_var`` still wins and makes the field read-only, so a deployment can
  keep credentials out of the database entirely.
- ``apply`` must validate fully before mutating the bound Settings instance.
  The live instance is mutated in place so a change takes effect on the next
  request without rebuilding the engine.
- A missing ``app_settings`` table is not fatal. Apps are constructed before
  migrations in several test/bootstrap paths, and a deployment that has not
  run the basic chain yet should still serve requests with static config.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.config_yaml import resolve_env_file
from cliver_playbook.app.basic.db.session import open_session
from cliver_playbook.app.basic.models.entities import AppSetting

logger = logging.getLogger("cliver_playbook.app.basic.runtime_settings")

_FIELD_TYPES = frozenset({"string", "integer", "number", "boolean", "enum", "json"})
_SECTION_KEY_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class SettingsError(RuntimeError):
    """Base class for runtime-settings failures (reported as a 400 by the API)."""


class UnknownSectionError(SettingsError):
    """No package registered the requested section key."""


class SettingsValidationError(SettingsError):
    """A requested value is unknown, read-only, or fails the section's rules."""


@dataclass(frozen=True)
class SettingsField:
    """One editable value in a module-owned settings section.

    ``env_var`` is the canonical environment variable that overrides the
    field (``CLIVER_RAG__EMBEDDER``). For a secret it names the variable a
    deployment can use to keep the credential out of the database: when set,
    the environment wins and the field becomes read-only. Otherwise the
    secret is write-only — accepted on update, persisted with the section,
    never returned.
    """

    name: str
    label: str
    type: str = "string"
    description: str = ""
    enum: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    env_var: str | None = None
    secret: bool = False
    # Optional presentation grouping. Fields sharing a key render together
    # under one heading; ``group_title`` is the English label a UI falls back
    # to when it has no translation. ``subgroup`` adds a nested heading inside
    # that group (for a large configuration with distinct purposes). Purely
    # presentational — persistence and validation remain per field.
    group: str | None = None
    group_title: str = ""
    subgroup: str | None = None
    subgroup_title: str = ""

    def __post_init__(self) -> None:
        if (
            not self.name
            or "." in self.name
            and not all(part.isidentifier() for part in self.name.split("."))
        ):
            raise ValueError(f"invalid settings field name: {self.name!r}")
        if not self.name[0].islower():
            raise ValueError(f"settings field name must start lowercase: {self.name!r}")
        if self.type not in _FIELD_TYPES:
            raise ValueError(f"{self.name}: unknown field type {self.type!r}")
        if self.type == "enum" and not self.enum:
            raise ValueError(f"{self.name}: an enum field needs at least one choice")
        if self.enum is not None:
            if self.type != "enum":
                raise ValueError(f"{self.name}: only an enum field may declare choices")
            if len(set(self.enum)) != len(self.enum):
                raise ValueError(f"{self.name}: duplicate enum choices")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"{self.name}: minimum exceeds maximum")
        if self.group is not None:
            if not re.match(_SECTION_KEY_PATTERN, self.group):
                raise ValueError(f"{self.name}: invalid group key {self.group!r}")
            if not self.group_title:
                raise ValueError(
                    f"{self.name}: a grouped field must declare group_title "
                    "(the untranslated UI fallback)"
                )
        elif self.group_title:
            raise ValueError(f"{self.name}: group_title requires a group key")
        if self.subgroup is not None:
            if self.group is None:
                raise ValueError(f"{self.name}: a subgroup requires a group key")
            if not re.match(_SECTION_KEY_PATTERN, self.subgroup):
                raise ValueError(f"{self.name}: invalid subgroup key {self.subgroup!r}")
            if not self.subgroup_title:
                raise ValueError(
                    f"{self.name}: a subgrouped field must declare subgroup_title "
                    "(the untranslated UI fallback)"
                )
        elif self.subgroup_title:
            raise ValueError(f"{self.name}: subgroup_title requires a subgroup key")


@dataclass(frozen=True)
class SettingsSection:
    """A package-owned slice of the settings surface.

    ``read`` returns the section's current values keyed by field name (raw —
    including secrets, for the configured/not-configured check). ``apply``
    receives a partial mapping and must validate the resulting full state
    before mutating the Settings instance.
    """

    key: str
    title: str
    description: str
    fields: Callable[[], Sequence[SettingsField]]
    read: Callable[[Any], Mapping[str, Any]]
    apply: Callable[[Any, Mapping[str, Any]], None]

    def __post_init__(self) -> None:
        if not re.match(_SECTION_KEY_PATTERN, self.key):
            raise ValueError(f"invalid settings section key: {self.key!r}")
        if not self.title:
            raise ValueError(f"settings section {self.key!r} needs a title")
        _validated_fields(self)


def _validated_fields(section: SettingsSection) -> tuple[SettingsField, ...]:
    """Materialise and structurally validate a section's field list."""
    fields = tuple(section.fields())
    if not fields:
        raise ValueError(f"settings section {section.key!r} has no fields")
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise ValueError(f"settings section {section.key!r} has duplicate field names")
    return fields


_sections: dict[str, SettingsSection] = {}


def register_settings_section(section: SettingsSection) -> None:
    """Register a module-owned settings section (idempotent for re-imports)."""
    existing = _sections.get(section.key)
    if existing is not None:
        if existing == section:
            return
        raise ValueError(
            f"settings section {section.key!r} is already registered by another "
            "package — section keys are process-wide"
        )
    _sections[section.key] = section


def settings_sections() -> tuple[SettingsSection, ...]:
    """Every registered section, in registration order."""
    return tuple(_sections.values())


def get_settings_section(key: str) -> SettingsSection | None:
    return _sections.get(key)


def env_snapshot(settings: Any | None = None) -> dict[str, str]:
    """Process environment plus the project .env, for env-managed detection.

    The process environment wins, matching the settings precedence. Empty
    values still count as "set" — an explicitly empty environment variable is
    an operator decision, not an absence.

    The dotenv layer follows the bound Settings instance's ``_env_file``:
    ``None`` means the instance deliberately disabled that layer (tests do
    this), so the project .env must not leak into the description either.
    """
    snapshot: dict[str, str] = dict(os.environ)
    resolved = settings if settings is not None else runtime.configured_settings()
    env_file: Any
    if resolved is not None and hasattr(resolved, "_env_file"):
        env_file = resolved._env_file
    else:
        env_file = resolve_env_file()
    if env_file is not None:
        try:
            for key, value in dotenv_values(env_file).items():
                if value is not None:
                    snapshot.setdefault(key, value)
        except OSError:  # pragma: no cover - resolve_env_file already checked
            logger.warning("could not read %s while describing runtime settings", env_file)
    return snapshot


def is_env_managed(field: SettingsField, env: Mapping[str, str]) -> bool:
    """True when the environment (or .env) explicitly sets this field."""
    if not field.env_var:
        return False
    return field.env_var in env or field.env_var.upper() in env


def _env_value(field: SettingsField, env: Mapping[str, str]) -> str | None:
    if not field.env_var:
        return None
    return env.get(field.env_var) or env.get(field.env_var.upper())


def _describe_field(
    field: SettingsField,
    raw: Mapping[str, Any],
    *,
    env: Mapping[str, str],
    persisted: Mapping[str, Any],
) -> dict[str, Any]:
    value = raw.get(field.name)
    managed = is_env_managed(field, env)
    # A secret is writable unless the environment supplies it: the UI accepts
    # a replacement and never receives the stored value back.
    read_only = managed
    if managed:
        source = "environment"
    elif field.name in persisted:
        source = "runtime"
    else:
        source = "config"
    return {
        "name": field.name,
        "label": field.label,
        "type": field.type,
        "description": field.description,
        "enum": list(field.enum) if field.enum else None,
        "minimum": field.minimum,
        "maximum": field.maximum,
        "env_var": field.env_var,
        "secret": field.secret,
        "group": field.group,
        "group_title": field.group_title,
        "subgroup": field.subgroup,
        "subgroup_title": field.subgroup_title,
        "read_only": read_only,
        "source": source,
        # A secret never leaves the process; its presence is the useful fact.
        # An environment value counts even when the running instance predates
        # it (the environment is authoritative at the next restart).
        "value": None if field.secret else value,
        "configured": (bool(_env_value(field, env) or value) if field.secret else None),
    }


def describe_section(
    section: SettingsSection,
    *,
    env: Mapping[str, str] | None = None,
    persisted: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public, secret-free representation of one section for the admin UI."""
    settings = runtime.configured_settings()
    if settings is None:
        raise RuntimeError("describe_section() requires a configured runtime")
    env = env_snapshot(settings) if env is None else env
    persisted = persisted or {}
    raw = section.read(settings)
    return {
        "key": section.key,
        "title": section.title,
        "description": section.description,
        "fields": [
            _describe_field(field, raw, env=env, persisted=persisted)
            for field in _validated_fields(section)
        ],
    }


def describe_sections(
    *,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    settings = _require_settings()
    env = env_snapshot(settings) if env is None else env
    overrides = overrides or {}
    return [
        describe_section(section, env=env, persisted=overrides.get(section.key, {}))
        for section in settings_sections()
    ]


def _validate_value(field: SettingsField, value: Any) -> None:
    """Type/range check before the owning section's model validation runs."""
    if field.type == "boolean":
        ok = isinstance(value, bool)
    elif field.type == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif field.type == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif field.type == "string":
        ok = isinstance(value, str)
    elif field.type == "enum":
        ok = isinstance(value, str) and value in (field.enum or ())
    else:  # json
        ok = isinstance(value, (dict, list, str, int, float, bool)) or value is None
    if not ok:
        expected = " or ".join(field.enum) if field.type == "enum" else field.type
        raise SettingsValidationError(
            f"{field.label} ({field.name}) must be {expected}, got {type(value).__name__}"
        )
    if field.type in {"integer", "number"}:
        if field.minimum is not None and value < field.minimum:
            raise SettingsValidationError(f"{field.label} must be at least {field.minimum:g}")
        if field.maximum is not None and value > field.maximum:
            raise SettingsValidationError(f"{field.label} must be at most {field.maximum:g}")


def _field_map(section: SettingsSection) -> dict[str, SettingsField]:
    return {field.name: field for field in _validated_fields(section)}


def redact_values(section: SettingsSection, values: Mapping[str, Any]) -> dict[str, Any]:
    """A copy safe to persist in the audit trail: secret values are masked.

    Section values are otherwise recorded verbatim so an operator can see
    what changed. ``api_key``-style fields must not end up in the audit log,
    whose readers and retention differ from the settings row's.
    """
    fields = _field_map(section)
    redacted: dict[str, Any] = {}
    for name, value in values.items():
        field = fields.get(name)
        if field is not None and field.secret:
            redacted[name] = "<redacted>" if value else ""
        else:
            redacted[name] = value
    return redacted


def _clean_values(
    section: SettingsSection,
    values: Mapping[str, Any],
    *,
    env: Mapping[str, str],
    for_write: bool,
) -> dict[str, Any]:
    """Filter a stored/proposed mapping to fields the runtime may apply.

    Unknown keys are ignored on load (a section may have dropped a field) but
    rejected on write. Env-managed fields — secrets included — are always
    dropped: the environment is authoritative for them. A persisted secret
    that the environment does not manage survives the load so the startup
    overlay can apply it.
    """
    fields = _field_map(section)
    clean: dict[str, Any] = {}
    for name, value in values.items():
        field = fields.get(name)
        if field is None:
            if for_write:
                raise SettingsValidationError(f"unknown setting: {name!r}")
            continue
        if is_env_managed(field, env):
            if for_write:
                raise SettingsValidationError(
                    f"{field.label} is managed by {field.env_var} and cannot be changed at runtime"
                )
            continue
        if for_write:
            _validate_value(field, value)
        clean[name] = value
    return clean


def _require_settings() -> Any:
    settings = runtime.configured_settings()
    if settings is None:
        raise RuntimeError("runtime settings require a configured runtime")
    return settings


async def load_overrides(db: AsyncSession | None = None) -> dict[str, dict[str, Any]]:
    """Read every persisted section row (empty when the table is absent)."""
    owns_session = db is None
    session = open_session() if db is None else db
    try:
        rows = (await session.execute(select(AppSetting))).scalars().all()
        return {row.section: dict(row.values or {}) for row in rows}
    finally:
        if owns_session:
            # Startup overlays must never fail on teardown: a session whose
            # connection could not be acquired (or belongs to another event
            # loop) may also fail to close, and that error must not replace
            # the read error the caller is about to handle.
            try:
                await session.close()
            except Exception:  # pragma: no cover - defensive teardown
                logger.warning("could not close the runtime-settings session", exc_info=True)


def is_missing_table(exc: SQLAlchemyError) -> bool:
    original = getattr(exc, "orig", None)
    pgcode = getattr(original, "pgcode", None)
    text = str(original or exc).lower()
    return (
        pgcode == "42P01"
        or "undefinedtable" in text
        or "no such table" in text
        or "does not exist" in text
    )


async def update_section(
    db: AsyncSession,
    section: SettingsSection,
    values: Mapping[str, Any],
    *,
    actor_id: int | None,
) -> dict[str, Any]:
    """Validate, apply live, and persist a partial section update.

    The caller owns the transaction (the admin API writes its audit row and
    commits both changes together). On a validation failure nothing is
    persisted and — because sections validate before mutating — the live
    settings are unchanged.
    """
    if not isinstance(values, Mapping):
        raise SettingsValidationError("values must be an object")
    settings = _require_settings()
    env = env_snapshot(settings)
    clean = _clean_values(section, values, env=env, for_write=True)

    row = await db.get(AppSetting, section.key)
    stored = dict(row.values or {}) if row is not None else {}
    merged = {**stored, **clean}
    # A value stored before its field became environment-managed must not
    # override the environment in-process.
    merged = _clean_values(section, merged, env=env, for_write=False)

    section.apply(settings, merged)

    if row is None:
        row = AppSetting(section=section.key, values=merged, updated_by=actor_id)
        db.add(row)
    else:
        row.values = merged
        row.updated_by = actor_id
    await db.flush()
    return merged


async def reset_section(
    db: AsyncSession, section: SettingsSection, *, actor_id: int | None
) -> None:
    """Delete the section's persisted row and restore the startup baseline."""
    settings = _require_settings()
    baseline = runtime.baseline_settings()
    if baseline is None:  # pragma: no cover - configure always stores one
        raise RuntimeError("runtime baseline is unavailable")
    env = env_snapshot(settings)
    baseline_values = dict(section.read(baseline))
    restore = _clean_values(section, baseline_values, env=env, for_write=False)
    section.apply(settings, restore)
    await db.execute(delete(AppSetting).where(AppSetting.section == section.key))
    await db.flush()


async def load_persisted_settings() -> None:
    """Apply every persisted override at startup (best effort).

    Called by each package's lifespan. A missing table (migrations not yet
    applied) is a warning, not a crash: the application still serves static
    configuration. Any other read failure is handled the same way — the
    overlay is an optimization, and no database condition at startup may
    prevent the process from serving. A bad row is logged and skipped for the
    same reason — one malformed section must not take the process down.
    """
    if not runtime.is_configured():
        return
    settings = runtime.configured_settings()
    try:
        overrides = await load_overrides()
    except Exception as exc:
        if isinstance(exc, SQLAlchemyError) and is_missing_table(exc):
            logger.warning(
                "app_settings table is missing; runtime settings overrides are disabled "
                "until the basic migration chain is applied"
            )
        else:
            logger.exception("could not read app_settings; continuing with static configuration")
        return

    env = env_snapshot(settings)
    for key, values in overrides.items():
        section = get_settings_section(key)
        if section is None:
            logger.warning(
                "app_settings row for unknown section %r ignored (owning package not installed?)",
                key,
            )
            continue
        try:
            clean = _clean_values(section, values, env=env, for_write=False)
            section.apply(settings, clean)
        except Exception:
            logger.exception(
                "could not apply persisted settings for section %r; using static configuration",
                key,
            )


@asynccontextmanager
async def settings_lifespan(_app: Any):
    """Lifespan wrapper: overlay persisted settings, then release the engine."""
    await load_persisted_settings()
    try:
        yield
    finally:
        await runtime.dispose()
