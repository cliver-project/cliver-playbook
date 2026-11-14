"""Project-owned registration request."""

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr | None = None
    display_name: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def _empty_email_becomes_none(cls, value: str | None) -> str | None:
        return None if value == "" else value
