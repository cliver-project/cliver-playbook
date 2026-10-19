"""Admin runtime settings: a thin, section-agnostic delegation layer.

This module owns the HTTP surface and the audit trail, nothing else. Each
package owns its section (``user.settings_section``, ``rag.settings_section``,
…): the package declares the fields, validates a proposed state, and applies
it to the live Settings instance. Adding an operator knob is therefore a
change inside the owning module, not in the identity package (ADR-0021).

Authorization is ``settings:read`` for inspection and ``settings:manage`` for
change/reset. The seeded admin role holds the ``*`` wildcard, so it passes
both; a narrower operator role can be granted just these two codes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.basic.runtime_settings import (
    SettingsError,
    SettingsSection,
    UnknownSectionError,
    describe_section,
    describe_sections,
    get_settings_section,
    is_missing_table,
    load_overrides,
    redact_values,
    reset_section,
    update_section,
)
from cliver_playbook.app.user.auth.audit import write_audit
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm
from cliver_playbook.app.user.schemas.settings import SettingsSectionRead, SettingsUpdate

router = APIRouter(prefix="/api/v1/admin/settings", tags=["admin"])


def _section_or_404(key: str) -> SettingsSection:
    section = get_settings_section(key)
    if section is None:
        raise HTTPException(status_code=404, detail=f"Unknown settings section: {key}")
    return section


def _settings_error(exc: SettingsError) -> HTTPException:
    status_code = 404 if isinstance(exc, UnknownSectionError) else 400
    return HTTPException(status_code=status_code, detail=str(exc))


async def _overrides(db: AsyncSession) -> dict[str, dict]:
    """Persisted sections; empty when migrations have not created the table."""
    try:
        return await load_overrides(db)
    except SQLAlchemyError as exc:
        if is_missing_table(exc):
            return {}
        raise


@router.get("", response_model=list[SettingsSectionRead])
async def list_settings(
    _viewer: Viewer = Depends(require_perm("settings:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Every registered section, described by its owning package."""
    return describe_sections(overrides=await _overrides(db))


@router.get("/{section_key}", response_model=SettingsSectionRead)
async def get_section(
    section_key: str,
    _viewer: Viewer = Depends(require_perm("settings:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    section = _section_or_404(section_key)
    persisted = (await _overrides(db)).get(section.key, {})
    return describe_section(section, persisted=persisted)


@router.put("/{section_key}", response_model=SettingsSectionRead)
async def update_settings(
    section_key: str,
    payload: SettingsUpdate,
    request: Request,
    viewer: Viewer = Depends(require_perm("settings:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate and apply a partial update, then persist it for restarts.

    ``update_section`` calls the owning package's ``apply`` before this
    endpoint writes anything, so an invalid request leaves both the live
    configuration and the stored overrides untouched.
    """
    section = _section_or_404(section_key)
    try:
        merged = await update_section(db, section, payload.values, actor_id=viewer.user_id)
    except SettingsError as exc:
        raise _settings_error(exc) from exc

    await write_audit(
        db,
        event="admin.settings.update",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"settings:{section.key}",
        # Secret fields are masked: the audit log has different readers and
        # retention from the app_settings row that legitimately stores them.
        detail={"values": redact_values(section, payload.values)},
        request=request,
    )
    await db.commit()
    return describe_section(section, persisted=merged)


@router.delete("/{section_key}", response_model=SettingsSectionRead)
async def reset_settings(
    section_key: str,
    request: Request,
    viewer: Viewer = Depends(require_perm("settings:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Drop the section's runtime overrides and restore the startup values.

    The startup values already include environment, ``.env``, ``app.yaml``,
    and defaults, so a reset can never resurrect a stale environment-beaten
    value.
    """
    section = _section_or_404(section_key)
    try:
        await reset_section(db, section, actor_id=viewer.user_id)
    except SettingsError as exc:
        raise _settings_error(exc) from exc

    await write_audit(
        db,
        event="admin.settings.reset",
        user_id=viewer.user_id,
        username=viewer.username,
        target=f"settings:{section.key}",
        request=request,
    )
    await db.commit()
    return describe_section(section)
