"""Pydantic schemas for /auth — request bodies + response envelopes.

Field constraints chosen to match the contract:
  - password: 8–128 chars on register (enforce minimum strength), 1–128 on
    login (don't reveal length policy at the auth boundary).
  - role: validated against the same CHECK constraint as the DB column.

Note on email validation: `pydantic.EmailStr` defers to `email-validator`
which (since v2.0) rejects RFC 6761 special-use TLDs like `.test`,
`.localhost`, `.example`, `.invalid`. Demos and internal accounts at FHH use
`@fhh.test` so we wrap email-validator with `test_environment=True` and
expose it as `EmailField` below — same RFC validation otherwise.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, BeforeValidator, Field


def _normalise_email(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("email must be a string")
    try:
        # check_deliverability=False — don't hit DNS during request handling.
        # test_environment=True — allow .test/.localhost/.example/.invalid.
        result = validate_email(
            v.strip(), check_deliverability=False, test_environment=True,
        )
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return result.normalized.lower()


EmailField = Annotated[str, BeforeValidator(_normalise_email)]


class RegisterRequest(BaseModel):
    email: EmailField
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)
    # Ignored for the very first user (auto-admin) and when caller is
    # non-admin. Otherwise routed through; admin can create either role.
    role: Optional[str] = Field(default=None, pattern="^(admin|operator)$")


class LoginRequest(BaseModel):
    email: EmailField
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds — matches security.JWT_EXPIRY_SECONDS
    user: UserResponse


class UserListResponse(BaseModel):
    users: list[UserResponse]
