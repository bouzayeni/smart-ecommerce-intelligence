"""One error format for every failure: {"error": {"code", "message", "request_id", "details"}}."""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

log = logging.getLogger("app.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def _body(request: Request, code: str, message: str, details=None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
            "details": details,
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), exc.status)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "error"
        )
        return JSONResponse(
            _body(request, code, str(exc.detail)),
            exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        return JSONResponse(_body(request, "validation_error", "Invalid request", details), 422)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            _body(request, "rate_limited", f"Rate limit exceeded: {exc.detail}"), 429
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Never leak internals (SQL, stack traces) to clients; the request id links to the log.
        log.exception(
            "Unhandled error", extra={"request_id": getattr(request.state, "request_id", None)}
        )
        return JSONResponse(_body(request, "internal_error", "Internal server error"), 500)
