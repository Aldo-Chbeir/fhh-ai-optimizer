"""/auth — bcrypt password hashing + JWT bearer tokens, asyncpg-backed.

Public entrypoint:
  from .router import router as auth_router
"""
from .router import router  # re-exported for convenience

__all__ = ["router"]
