"""Pure-function crypto helpers — no DB, no FastAPI imports.

Two responsibilities:
  1. bcrypt password hashing (`hash_password`, `verify_password`).
  2. JWT issuance and decode (`create_access_token`, `decode_access_token`).

The JWT secret is read fresh from `os.getenv("JWT_SECRET")` on every call so
operators can rotate the key by editing .env + restarting the backend (no
code change). There is intentionally NO default — missing JWT_SECRET raises
RuntimeError at first use.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from ..errors import InvalidToken, TokenExpired

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 86400  # 24h


def _jwt_secret() -> str:
    """Read JWT_SECRET fresh — no module-level cache, no fallback default."""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not set in the environment. Generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
            "and add it to .env before starting the backend."
        )
    return secret


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash. Cost factor uses bcrypt's default (12)."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time bcrypt compare. False on any decode error."""
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001 — malformed hash → reject, don't crash
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(user_id: str, email: str, role: str) -> str:
    """Issue an HS256 JWT for `user_id`. 24h expiry. Claims: sub, email, role, iat, exp."""
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub":   str(user_id),
        "email": email,
        "role":  role,
        "iat":   int(now.timestamp()),
        "exp":   int((now + timedelta(seconds=JWT_EXPIRY_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode + validate. Returns {user_id, email, role}.

    Raises:
      TokenExpired (401, code=token_expired)  — exp claim has passed
      InvalidToken (401, code=invalid_token)  — signature mismatch or malformed
    """
    try:
        claims = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken(f"Token decode failed: {exc.__class__.__name__}") from exc

    sub = claims.get("sub")
    email = claims.get("email")
    role = claims.get("role")
    if not sub or not email or not role:
        raise InvalidToken("Token payload missing required claims.")
    return {"user_id": str(sub), "email": str(email), "role": str(role)}
