"""The identity package's runtime settings section (ADR-0021).

Ownership: this module defines what an administrator may change about identity
policy, and how those values are validated and applied. The generic settings
framework in ``basic.runtime_settings`` never knows these fields; the admin API
only delegates to this section. The same ownership rule applies to every
composing package (see ``rag.settings_section``).

Only non-secret, runtime-safe fields live here. ``secret_key``,
``initial_admin_password``, and the OIDC client secrets stay environment-only —
they are bootstrap or credential values, not operator knobs. Changing
``web_base_url`` affects the next login redirect; the token TTL applies to
newly issued web sessions, not to tokens already in the wild.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cliver_playbook.app.basic.runtime_settings import (
    SettingsField,
    SettingsSection,
    SettingsValidationError,
    register_settings_section,
)

SECTION_KEY = "user"


class _UserRuntimeSettings(BaseModel):
    """Validation model for the editable identity policy."""

    token_ttl_days: int = Field(ge=1, le=3650)
    login_lockout_threshold: int = Field(ge=1, le=100)
    login_lockout_minutes: int = Field(ge=1, le=1440)
    web_base_url: str = Field(min_length=1, max_length=255)


def _fields() -> tuple[SettingsField, ...]:
    return (
        SettingsField(
            name="token_ttl_days",
            label="Web session lifetime (days)",
            type="integer",
            minimum=1,
            maximum=3650,
            description="Lifetime of newly issued browser and static tokens.",
            env_var="CLIVER_TOKEN_TTL_DAYS",
        ),
        SettingsField(
            name="login_lockout_threshold",
            label="Failed logins before lockout",
            type="integer",
            minimum=1,
            maximum=100,
            description="Consecutive failed password attempts that lock an account.",
            env_var="CLIVER_LOGIN_LOCKOUT_THRESHOLD",
        ),
        SettingsField(
            name="login_lockout_minutes",
            label="Lockout duration (minutes)",
            type="integer",
            minimum=1,
            maximum=1440,
            description="How long an account stays locked after the threshold is reached.",
            env_var="CLIVER_LOGIN_LOCKOUT_MINUTES",
        ),
        SettingsField(
            name="web_base_url",
            label="Frontend base URL",
            type="string",
            description=(
                "Where the SPA lives; the backend redirects here after OIDC login. "
                "Set it when running behind a proxy that rewrites Host."
            ),
            env_var="CLIVER_WEB_BASE_URL",
        ),
    )


def _read(settings: Any) -> dict[str, Any]:
    return {
        "token_ttl_days": settings.token_ttl_days,
        "login_lockout_threshold": settings.login_lockout_threshold,
        "login_lockout_minutes": settings.login_lockout_minutes,
        "web_base_url": settings.web_base_url,
    }


def _apply(settings: Any, values: dict[str, Any]) -> None:
    merged = {**_read(settings), **values}
    try:
        validated = _UserRuntimeSettings.model_validate(merged)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise SettingsValidationError(f"invalid identity settings: {details}") from exc
    for name in _UserRuntimeSettings.model_fields:
        setattr(settings, name, getattr(validated, name))


USER_SETTINGS_SECTION = SettingsSection(
    key=SECTION_KEY,
    title="Identity and access",
    description=(
        "Session lifetime, brute-force lockout, and the frontend URL used by "
        "external sign-in redirects."
    ),
    fields=_fields,
    read=_read,
    apply=_apply,
)

register_settings_section(USER_SETTINGS_SECTION)
