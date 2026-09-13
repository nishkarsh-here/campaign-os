"""One error shape for the whole API (API_SPEC §Conventions).

Handlers live here so no route ever constructs an error body by hand, and so
the rule "user-safe message out, detail to the logs" is applied in exactly one
place.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import AppError
from app.logging import get_logger, request_id_ctx
from app.providers.base import ProviderError

log = get_logger(__name__)


def error_body(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_ctx.get() or "",
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        if exc.detail:
            log.warning("app_error", code=exc.code, detail=exc.detail)
        return JSONResponse(
            status_code=exc.http_status,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(ProviderError)
    async def _provider_error(_request: Request, exc: ProviderError) -> JSONResponse:
        # Vendor detail stays in the log; the client gets a usable sentence.
        log.error("provider_error", code=exc.code, provider=exc.provider, detail=exc.detail)
        return JSONResponse(status_code=502, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", ())[1:]) or "body"
        return JSONResponse(
            status_code=400,
            content=error_body(
                "VALIDATION_FAILED",
                first.get("msg", "Request validation failed."),
                {"field": field},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT"}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(codes.get(exc.status_code, "INTERNAL"), str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # Never leak an internal message or stack to the client.
        log.exception("unhandled_error", error=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL", "Something went wrong on our side."),
        )
