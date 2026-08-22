"""Standardized Safe Error Handling Subsystem for BEACON.

Ensures consistent error payloads, distinct error categories, correlation tracking,
and zero leakage of internal stack traces, credentials, or file paths.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from .logging_config import scrub_secrets, current_request_id, get_logger

logger = get_logger("beacon.errors")


class ErrorCategory(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    CERTIFICATION_FAILURE = "CERTIFICATION_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    STORAGE_FAILURE = "STORAGE_FAILURE"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class StandardErrorResponse(BaseModel):
    """Consistent, production-grade error payload structure with backward-compatible detail field."""
    error_code: str
    category: ErrorCategory
    message: str
    detail: Optional[str] = None
    request_id: str = Field(default_factory=lambda: current_request_id.get() or "REQ-UNKNOWN")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Optional[dict[str, Any]] = None

    def __init__(self, **data: Any):
        if "detail" not in data and "message" in data:
            data["detail"] = data["message"]
        elif "message" not in data and "detail" in data:
            data["message"] = str(data["detail"])
        super().__init__(**data)


class BeaconOperationalError(Exception):
    """Base exception for operational and runtime errors in BEACON."""
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.status_code = status_code
        self.details = details or {}


class ResourceLimitError(BeaconOperationalError):
    """Raised when a dataset or request exceeds safe configured workload limits."""
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE_LIMIT,
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            details=details,
        )


class DependencyUnavailableError(BeaconOperationalError):
    """Raised when a mandatory backend dependency is unavailable."""
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


def _map_http_status_to_category(status_code: int) -> ErrorCategory:
    if status_code == 400:
        return ErrorCategory.VALIDATION_ERROR
    elif status_code in (401, 403):
        return ErrorCategory.AUTHORIZATION_ERROR
    elif status_code == 404:
        return ErrorCategory.NOT_FOUND
    elif status_code == 409:
        return ErrorCategory.CONFLICT
    elif status_code == 412:
        return ErrorCategory.PRECONDITION_FAILED
    elif status_code in (413, 422):
        return ErrorCategory.RESOURCE_LIMIT if status_code == 413 else ErrorCategory.VALIDATION_ERROR
    elif status_code == 408 or status_code == 504:
        return ErrorCategory.TIMEOUT
    elif status_code == 503:
        return ErrorCategory.DEPENDENCY_UNAVAILABLE
    elif status_code == 502:
        return ErrorCategory.PROVIDER_FAILURE
    return ErrorCategory.INTERNAL_ERROR


def register_error_handlers(app: FastAPI) -> None:
    """Registers standard global exception handlers on the FastAPI application."""

    @app.exception_handler(BeaconOperationalError)
    async def beacon_operational_error_handler(request: Request, exc: BeaconOperationalError):
        req_id = current_request_id.get() or request.headers.get("X-Correlation-ID", "")
        payload = StandardErrorResponse(
            error_code=exc.category.value,
            category=exc.category,
            message=scrub_secrets(exc.message),
            request_id=req_id,
            details=exc.details,
        )
        logger.warning(f"Operational error [{exc.category.value}]: {scrub_secrets(exc.message)}")
        return JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(mode="json"),
            headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
        )

    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        req_id = current_request_id.get() or request.headers.get("X-Correlation-ID", "")
        category = _map_http_status_to_category(exc.status_code)
        
        detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        payload = StandardErrorResponse(
            error_code=f"HTTP_{exc.status_code}",
            category=category,
            message=scrub_secrets(detail_msg),
            request_id=req_id,
            details={"status_code": exc.status_code},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(mode="json"),
            headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        req_id = current_request_id.get() or request.headers.get("X-Correlation-ID", "")
        sanitized_errors = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            sanitized_errors.append({"field": loc, "issue": err.get("msg", "Invalid field value")})

        payload = StandardErrorResponse(
            error_code="VALIDATION_ERROR",
            category=ErrorCategory.VALIDATION_ERROR,
            message="Request payload failed validation schema.",
            request_id=req_id,
            details={"field_errors": sanitized_errors},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=payload.model_dump(mode="json"),
            headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        req_id = current_request_id.get() or request.headers.get("X-Correlation-ID", "")
        # Log the full exception with secret scrubbing on the server only
        logger.error(
            f"Unhandled server exception on {request.method} {request.url.path} (Request ID: {req_id}): {scrub_secrets(str(exc))}",
            exc_info=True,
        )
        # Return a safe sanitized payload to the client without stack traces
        payload = StandardErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            category=ErrorCategory.INTERNAL_ERROR,
            message="An unexpected server error occurred during processing. Please reference the request ID.",
            request_id=req_id,
            details={"path": request.url.path},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=payload.model_dump(mode="json"),
            headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
        )
