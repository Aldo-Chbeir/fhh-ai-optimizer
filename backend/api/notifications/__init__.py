"""Transactional email — Resend SDK + dedupe + audit log.

Public entrypoint:
  from .router import router as notifications_router
"""
from .router import router

__all__ = ["router"]
