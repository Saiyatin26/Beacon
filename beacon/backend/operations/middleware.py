"""FastAPI Middleware for Request Correlation and Workload Protection."""

import re
import time
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from common.config import settings
from .logging_config import current_request_id, current_project_id

CORRELATION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{4,64}$")


def get_correlation_id() -> str:
    """Returns the current request's correlation ID or generates a standalone one."""
    return current_request_id.get() or f"REQ-{uuid.uuid4().hex[:12]}"


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Assigns and propagates correlation IDs across request execution contexts."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Extract or generate Correlation ID
        incoming_id = (
            request.headers.get("X-Correlation-ID")
            or request.headers.get("X-Request-ID")
            or ""
        ).strip()

        if incoming_id and CORRELATION_ID_REGEX.match(incoming_id):
            request_id = incoming_id
        else:
            request_id = f"REQ-{uuid.uuid4().hex[:12]}"

        # 2. Extract Project ID context if present in query or headers
        project_id = request.headers.get("X-Project-ID") or request.query_params.get("project_id") or ""

        # 3. Store in ContextVars
        token_req = current_request_id.set(request_id)
        token_proj = current_project_id.set(project_id)

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            current_request_id.reset(token_req)
            current_project_id.reset(token_proj)

        # 4. Attach headers to response
        response.headers["X-Correlation-ID"] = request_id
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
        return response


class WorkloadLimiterMiddleware(BaseHTTPMiddleware):
    """Enforces request body size limits to protect backend memory and workload capacity."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        max_bytes = getattr(settings, "max_request_body_bytes", 15 * 1024 * 1024)
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                length_int = int(content_length)
                if length_int > max_bytes:
                    req_id = get_correlation_id()
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error_code": "RESOURCE_LIMIT_EXCEEDED",
                            "category": "RESOURCE_LIMIT",
                            "message": f"Request body size ({length_int} bytes) exceeds maximum configured limit of {max_bytes} bytes.",
                            "request_id": req_id,
                            "details": {"max_bytes": max_bytes, "received_bytes": length_int},
                        },
                        headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
                    )
            except ValueError:
                pass

        return await call_next(request)
