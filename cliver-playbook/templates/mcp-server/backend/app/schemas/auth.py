"""Pydantic schemas for the identity domain (request/response contracts).

Never expose `password_hash` or `token_hash` — response models omit them by
construction, so a future field addition to the ORM cannot leak them.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Passwords: length-only policy. Composition rules (symbols, mixed case) are
# NIST SP 800-63B discouraged; length is the knob that matters.
_PASSWORD_FIELD = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = _PASSWORD_FIELD


class LoginResponse(BaseModel):
    """Body of POST /auth/login and the OIDC callback fragment."""

    token: str
    must_change_password: bool
    user: "UserRead"


class OAuthAuthorizeRequest(BaseModel):
    """SPA authorize page submitting credentials against an oauth blob."""

    blob: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class MeResponse(BaseModel):
    user: "UserRead"


# ---------------------------------------------------------------------------
# Users (admin)
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    password: str = _PASSWORD_FIELD
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    display_name: str = Field(default="", max_length=128)
    role_ids: list[int] = Field(default_factory=list)
    # New accounts start with a forced password change unless the creator
    # explicitly opts out (e.g. seeding demo accounts).
    must_change_password: bool = True

    @field_validator("email", "phone")
    @classmethod
    def _empty_string_becomes_none(cls, v: str | None) -> str | None:
        # Sending "" clears the field; pydantic would otherwise reject an
        # empty email before the endpoint ever sees it.
        return None if v == "" else v


class UserUpdate(BaseModel):
    """All fields optional; None = leave unchanged."""

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    display_name: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None
    role_ids: list[int] | None = None

    @field_validator("email", "phone")
    @classmethod
    def _empty_string_becomes_none(cls, v: str | None) -> str | None:
        # Sending "" clears the field; pydantic would otherwise reject an
        # empty email before the endpoint ever sees it.
        return None if v == "" else v


class ProfileUpdate(BaseModel):
    """Self-service profile edit (PATCH /auth/profile).

    Deliberately narrow: no username (stable identity), no is_active, no
    roles — those stay admin-only. Email/phone accept "" to clear.
    """

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("email", "phone")
    @classmethod
    def _empty_string_becomes_none(cls, v: str | None) -> str | None:
        return None if v == "" else v


class ResetPasswordRequest(BaseModel):
    new_password: str = _PASSWORD_FIELD


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    phone: str | None
    display_name: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    role_codes: list[str] = Field(default_factory=list)
    # Flattened permission codes so the SPA can gate UI affordances. The
    # SERVER remains the enforcement point; this is display-only.
    permissions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Roles and permissions (admin)
# ---------------------------------------------------------------------------


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=255)
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    permission_codes: list[str] | None = None


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    is_system: bool
    created_at: datetime
    permission_codes: list[str] = Field(default_factory=list)


class PermissionRead(BaseModel):
    code: str
    name: str
    group: str


# ---------------------------------------------------------------------------
# OAuth provider administration
# ---------------------------------------------------------------------------


class OauthClientRead(BaseModel):
    """A dynamically registered client (RFC 7591). The client secret is NEVER
    exposed — redirect URIs / grant types come from the registration metadata
    dump, which is stored minus the secret."""

    client_id: str
    client_name: str
    redirect_uris: list[str] = Field(default_factory=list)
    grant_types: list[str] = Field(default_factory=list)
    created_at: datetime


class OauthGrantRead(BaseModel):
    """One live grant: an unrevoked, unexpired refresh-token chain a user
    authorized for a client. Several rows for the same pair mean the user
    authorized that client more than once (each flow is its own chain)."""

    id: int
    user_id: int
    username: str
    client_id: str
    client_name: str
    scopes: list[str] = Field(default_factory=list)
    granted_at: datetime
    expires_at: datetime


class OauthGrantRevokeRequest(BaseModel):
    """Revoke every live grant for a (user, client) pair — refresh chains and
    OAuth access tokens both. Idempotent: an already-revoked pair is a no-op."""

    user_id: int
    client_id: str = Field(min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Linked external identities (self-service, profile page)
# ---------------------------------------------------------------------------


class IdentityLinkStart(BaseModel):
    """Response of POST /auth/identities/{provider}/link: the IdP authorize
    URL for the SPA to navigate to — a full-page navigation, because the
    redirect chain must leave the SPA for the IdP and return to the backend
    callback (same shape as a login, different signed state)."""

    redirect_url: str


class LinkedIdentityRead(BaseModel):
    """One external identity attached to the viewer's account."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    # Display label resolved through the settings registry (including
    # disabled presets); identities whose key left the config fall back to
    # the raw key. Display-only — the provider key is the stable value.
    provider_label: str
    email: str
    display_name: str
    linked_at: datetime
    # True when unlinking this row would leave an OIDC-only account with no
    # credential at all — DELETE refuses it with 409. Display-only hint; the
    # server re-checks on the DELETE itself.
    is_last_credential: bool


# ---------------------------------------------------------------------------
# Audit (admin)
# ---------------------------------------------------------------------------


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    user_id: int | None
    username: str
    event: str
    target: str
    ok: bool
    error: str
    detail: dict
    ip: str
    user_agent: str


class AuditLogPage(BaseModel):
    items: list[AuditLogRead]
    total: int


LoginResponse.model_rebuild()
MeResponse.model_rebuild()
