"""Domain exceptions + global exception handlers.

All errors are serialised in the contract shape:
    { "error": { "code": "...", "message": "...", "status": <int> } }
"""
from __future__ import annotations

import logging
import traceback
from typing import Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("fhh.api.error")


class APIError(Exception):
    """Base class for contract-defined errors."""

    code: str = "internal_error"
    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: Optional[str] = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class MachineNotFound(APIError):
    code = "machine_not_found"
    status_code = 404

    def __init__(self, machine_id: str) -> None:
        super().__init__(f"No machine exists with ID '{machine_id}'.")


class ComponentNotFound(APIError):
    code = "component_not_found"
    status_code = 404

    def __init__(self, machine_id: str, component_id: str) -> None:
        super().__init__(
            f"No component '{component_id}' on machine '{machine_id}'."
        )


class SensorNotFound(APIError):
    code = "invalid_request"
    status_code = 400

    def __init__(self, sensor_type: str) -> None:
        super().__init__(f"Unknown sensor_type '{sensor_type}'.")


class AlertNotFound(APIError):
    code = "invalid_request"
    status_code = 404

    def __init__(self, alert_id: str) -> None:
        super().__init__(f"No alert exists with ID '{alert_id}'.")


class SKUNotFound(APIError):
    code = "sku_not_found"
    status_code = 404

    def __init__(self, sku: str) -> None:
        super().__init__(f"No product exists with SKU '{sku}'.")


class MarketNotFound(APIError):
    code = "invalid_request"
    status_code = 404

    def __init__(self, market_id: str) -> None:
        super().__init__(f"Unknown market '{market_id}'.")


class ConversationNotFound(APIError):
    code = "conversation_not_found"
    status_code = 404

    def __init__(self, cid: str) -> None:
        super().__init__(f"No conversation with ID '{cid}'.")


class InvalidRequest(APIError):
    code = "invalid_request"
    status_code = 400


def _err(code: str, message: str, status_: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_,
        content={"error": {"code": code, "message": message, "status": status_}},
    )


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error_handler(_req: Request, exc: APIError):
        return _err(exc.code, exc.message, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_handler(_req: Request, exc: StarletteHTTPException):
        # Map common HTTP statuses to contract codes
        code_map = {
            400: "invalid_request",
            404: "invalid_request",
            429: "rate_limited",
            503: "model_unavailable",
        }
        code = code_map.get(exc.status_code, "internal_error")
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _err(code, msg, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_req: Request, exc: RequestValidationError):
        # Build a readable summary of the validation failures.
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []))
            msgs.append(f"{loc}: {err.get('msg')}")
        msg = "; ".join(msgs) or "Validation failed."
        return _err("validation_error", msg, status.HTTP_422_UNPROCESSABLE_ENTITY)

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):
        log.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
        return _err(
            "internal_error",
            "An unexpected server error occurred.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
