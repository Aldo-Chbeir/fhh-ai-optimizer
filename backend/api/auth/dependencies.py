"""FastAPI dependencies — extract bearer token, resolve user, gate by role.

Two callables exposed to routers:
  - get_current_user: returns the user dict for the bearer token's `sub`.
                      Raises 401 if token is missing/expired/invalid OR the
                      underlying account has been deactivated.
  - require_role(...): factory returning a dependency that adds a 403 gate
                       on top of get_current_user.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from ..db import get_pool
from ..errors import Forbidden, InvalidToken
from .security import decode_access_token
from .services import get_user_by_id

# auto_error=True → FastAPI raises 401 immediately when the Authorization
# header is missing. Our exception handler maps that to code=auth_required
# via the AuthRequired-equivalent path (Starlette 401 → "unauthorized");
# we override the message in router.py where we want the precise auth_required
# code on /auth/register's no-token branch.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)


def _get_pool_dep() -> asyncpg.Pool:
    """Wrap get_pool so FastAPI's DI sees a callable dependency."""
    return get_pool()


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> dict:
    """Decode the bearer token and load the matching app_users row.

    Raises 401/invalid_token if the token decodes to a user that no longer
    exists or has been deactivated — that way old tokens stop working as
    soon as an admin disables an account.
    """
    payload = decode_access_token(token)
    try:
        user_uuid = UUID(payload["user_id"])
    except (KeyError, ValueError) as exc:
        raise InvalidToken("Token subject is not a valid user id.") from exc

    user = await get_user_by_id(pool, user_uuid)
    if user is None or not user["is_active"]:
        raise InvalidToken("Token user no longer exists or is deactivated.")
    return user


def require_role(*allowed_roles: str):
    """Factory: returns a dependency that 403s if user.role not in allowed."""
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles:
            raise Forbidden(
                f"This endpoint requires one of: {', '.join(allowed_roles)}."
            )
        return user
    return _dep
