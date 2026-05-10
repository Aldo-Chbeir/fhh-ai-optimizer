"""/auth router — register, login, me, list users.

Bootstrap rule: the very first call to /auth/register (when the table is
empty) creates an admin without requiring authentication. After that, only
admins can register new users, and the role is admin-controlled.
"""
from __future__ import annotations

from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, status

from ..db import get_pool
from ..errors import (
    AuthRequired, EmailAlreadyExists, Forbidden, InvalidCredentials,
)
from .dependencies import _get_pool_dep, get_current_user, require_role
from .models import (
    LoginRequest, RegisterRequest, TokenResponse, UserListResponse, UserResponse,
)
from .security import (
    JWT_EXPIRY_SECONDS, create_access_token, decode_access_token, verify_password,
)
from .services import (
    count_users, create_user, get_user_by_email, list_users, touch_last_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_to_response(u: dict) -> UserResponse:
    return UserResponse(
        id=u["id"], email=u["email"], role=u["role"],
        full_name=u["full_name"], is_active=u["is_active"],
        created_at=u["created_at"], last_login_at=u["last_login_at"],
    )


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    authorization: Optional[str] = Header(default=None),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> UserResponse:
    """Create a new account.

    First call (empty table) → auto-admin, no auth required, body.role ignored.
    Subsequent calls → must present an admin bearer token. body.role chooses
    "admin" or "operator"; defaults to "operator".
    """
    n = await count_users(pool)

    if n == 0:
        role = "admin"
    else:
        # Manual bearer extraction: we can't use Depends(get_current_user) here
        # because the bootstrap path needs to *skip* auth. Header gives us the
        # raw value; we parse + validate only when it exists.
        if not authorization:
            raise AuthRequired()
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthRequired()
        claims = decode_access_token(token)  # raises 401 if bad
        if claims["role"] != "admin":
            raise Forbidden("Only admins can create new accounts.")
        role = body.role or "operator"

    if await get_user_by_email(pool, body.email):
        raise EmailAlreadyExists(body.email)

    try:
        user = await create_user(
            pool,
            email=body.email, password=body.password,
            role=role, full_name=body.full_name,
        )
    except asyncpg.UniqueViolationError as exc:
        # Race: someone registered the same email between our check + insert.
        raise EmailAlreadyExists(body.email) from exc

    return _user_to_response(user)


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> TokenResponse:
    user = await get_user_by_email(pool, body.email)
    # Single failure mode for "no user", "deactivated", or "wrong password" —
    # InvalidCredentials always returns the same message + code so /auth/login
    # can't be used to enumerate which emails have accounts.
    if user is None or not user["is_active"]:
        raise InvalidCredentials()
    if not verify_password(body.password, user["password_hash"]):
        raise InvalidCredentials()

    from uuid import UUID
    await touch_last_login(pool, UUID(user["id"]))
    token = create_access_token(user["id"], user["email"], user["role"])
    # last_login_at on `user` is the OLD value (we updated after fetching).
    # Reflect "just now" so the response matches reality without a re-fetch.
    from datetime import datetime, timezone
    user["last_login_at"] = datetime.now(tz=timezone.utc)

    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRY_SECONDS,
        user=_user_to_response(user),
    )


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)) -> UserResponse:
    return _user_to_response(user)


# ---------------------------------------------------------------------------
# GET /auth/users  — admin only
# ---------------------------------------------------------------------------

@router.get("/users", response_model=UserListResponse)
async def get_users(
    _admin: dict = Depends(require_role("admin")),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> UserListResponse:
    rows = await list_users(pool)
    return UserListResponse(users=[_user_to_response(r) for r in rows])
