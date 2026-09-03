from datetime import datetime, timezone
import logging
import re
import time
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from common.config import settings
from .logging_config import (
    current_request_id,
    current_project_id,
    current_user_id,
    log_operational_event,
    sanitize_log_string,
    scrub_secrets,
)
from .metrics import operational_metrics


logger = logging.getLogger("beacon.operations.http")

CORRELATION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{4,64}$")


def get_correlation_id() -> str:
    """Returns the current request's correlation ID or generates a standalone one."""
    return current_request_id.get() or f"REQ-{uuid.uuid4().hex[:12]}"


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Assigns correlation IDs, measures monotonic duration, records operational metrics,
    and logs request lifecycles with secret scrubbing.
    """

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

        # 2. ContextVars initialization (do NOT trust client-supplied project headers/query params as authoritative)
        token_req = current_request_id.set(request_id)
        token_proj = current_project_id.set("")
        token_user = current_user_id.set("")

        start_time = time.perf_counter()
        status_code = 500
        is_slow = False
        elapsed_ms = 0.0

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            status_code = 500
            req_id = current_request_id.get() or request_id
            logger.error(
                f"Unhandled server exception on {request.method} {request.url.path} (Request ID: {req_id}): {scrub_secrets(str(exc))}",
                exc_info=True,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "category": "INTERNAL_ERROR",
                    "message": "An internal server error occurred. Please reference the request ID.",
                    "detail": "An internal server error occurred. Please reference the request ID.",
                    "request_id": req_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": {"path": request.url.path},
                },
                headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
            )

        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            slow_threshold = getattr(settings, "slow_request_threshold_ms", 2000.0)
            is_slow = elapsed_ms >= slow_threshold
            trusted_project_id = current_project_id.get() or None
            trusted_user_id = current_user_id.get() or None

            # Record operational HTTP metrics (low-cardinality labels)
            if getattr(settings, "metrics_enabled", True):
                operational_metrics.record_http_request(
                    method=request.method,
                    status_code=status_code,
                    duration_ms=elapsed_ms,
                    is_slow=is_slow,
                    project_id=trusted_project_id,
                )
                if status_code == 401:
                    operational_metrics.record_auth_failure()
                elif status_code == 403:
                    operational_metrics.record_auth_denied()

            # Structured request logging
            clean_path = sanitize_log_string(request.url.path)
            log_level = logging.WARNING if (status_code >= 500 or is_slow) else logging.INFO
            event_name = "slow_request_detected" if is_slow else "http_request_completed"

            log_operational_event(
                event=event_name,
                level=log_level,
                logger_name="beacon.operations.http",
                project_id=trusted_project_id,
                user_id=trusted_user_id,
                duration_ms=round(elapsed_ms, 2),
                outcome=f"HTTP_{status_code}",
                message=f"{request.method} {clean_path} returned {status_code} in {elapsed_ms:.2f}ms",
                method=request.method,
                path=clean_path,
                status_code=status_code,
            )

            current_request_id.reset(token_req)
            current_project_id.reset(token_proj)
            current_user_id.reset(token_user)

        # 4. Attach headers to response
        response.headers["X-Correlation-ID"] = request_id
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
        return response


class WorkloadLimiterMiddleware(BaseHTTPMiddleware):
    """Enforces request body size limits to protect backend memory and workload capacity.
    Protects against both oversized Content-Length headers and chunked streaming requests.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        max_bytes = getattr(settings, "max_request_body_bytes", 15 * 1024 * 1024)
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                length_int = int(content_length)
                if length_int > max_bytes:
                    req_id = get_correlation_id()
                    operational_metrics.record_rate_limit_hit()
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error_code": "RESOURCE_LIMIT_EXCEEDED",
                            "category": "RESOURCE_LIMIT",
                            "message": f"Request body size ({length_int} bytes) exceeds maximum configured limit of {max_bytes} bytes.",
                            "detail": f"Request body size ({length_int} bytes) exceeds maximum configured limit of {max_bytes} bytes.",
                            "request_id": req_id,
                            "details": {"max_bytes": max_bytes, "received_bytes": length_int},
                        },
                        headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
                    )
                # Content-Length is present and within limit: pass through without re-wrapping
                return await call_next(request)
            except ValueError:
                pass

        # Stream byte limit enforcement for chunked or indeterminate transfers without Content-Length
        bytes_received = 0
        original_receive = request._receive

        async def limited_receive():
            nonlocal bytes_received
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > max_bytes:
                    req_id = get_correlation_id()
                    operational_metrics.record_rate_limit_hit()
                    raise HTTPException(
                        status_code=413,
                        detail=f"Streaming request body size exceeded maximum limit of {max_bytes} bytes.",
                    )
            return message

        request._receive = limited_receive

        try:
            return await call_next(request)
        except HTTPException as exc:
            if exc.status_code == 413:
                req_id = get_correlation_id()
                return JSONResponse(
                    status_code=413,
                    content={
                        "error_code": "RESOURCE_LIMIT_EXCEEDED",
                        "category": "RESOURCE_LIMIT",
                        "message": str(exc.detail),
                        "detail": str(exc.detail),
                        "request_id": req_id,
                        "details": {"max_bytes": max_bytes},
                    },
                    headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
                )
            raise

