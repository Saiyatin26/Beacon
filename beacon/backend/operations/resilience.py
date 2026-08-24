"""Phase 19 — Resilience, Bounded Retry, and Safe Timeout Subsystem for BEACON.

Provides deterministic retry mechanics with exponential backoff and jitter,
failure classification (retryable vs permanent), and safe execution timeout boundaries.
"""

import concurrent.futures
import logging
import random
import sqlite3
import time
import urllib.error
from typing import Any, Callable, Optional, Tuple, TypeVar

from fastapi import HTTPException
from common.config import settings
from .errors import (
    BeaconOperationalError,
    DependencyUnavailableError,
    ErrorCategory,
    IdempotencyConflictError,
    OperationTimeoutError,
    ResourceLimitError,
    StateTransitionError,
)
from .logging_config import log_operational_event, scrub_secrets

logger = logging.getLogger("beacon.resilience")

T = TypeVar("T")


def classify_failure(exc: Exception) -> Tuple[bool, ErrorCategory]:
    """Classifies an exception as either retryable (transient) or permanent (non-retryable).
    Returns a tuple of (is_retryable, ErrorCategory).
    """
    # 1. Explicit BEACON Operational Errors
    if isinstance(exc, (StateTransitionError, IdempotencyConflictError, ResourceLimitError)):
        return False, exc.category

    if isinstance(exc, OperationTimeoutError):
        return True, ErrorCategory.TIMEOUT

    if isinstance(exc, DependencyUnavailableError):
        return True, ErrorCategory.DEPENDENCY_UNAVAILABLE

    # 2. FastAPI / Starlette HTTP Exceptions
    if isinstance(exc, HTTPException):
        code = exc.status_code
        # Non-retryable client and deterministic business errors
        if code in (400, 401, 403, 404, 405, 409, 412, 413, 422):
            if code in (401, 403):
                return False, ErrorCategory.AUTHORIZATION_ERROR
            elif code in (400, 422):
                return False, ErrorCategory.VALIDATION_ERROR
            elif code == 404:
                return False, ErrorCategory.NOT_FOUND
            elif code == 409:
                return False, ErrorCategory.CONFLICT
            elif code == 413:
                return False, ErrorCategory.RESOURCE_LIMIT
            return False, ErrorCategory.VALIDATION_ERROR
        # Retryable gateway/proxy and server errors
        if code in (408, 502, 503, 504):
            return True, ErrorCategory.TIMEOUT if code in (408, 504) else ErrorCategory.DEPENDENCY_UNAVAILABLE
        return False, ErrorCategory.INTERNAL_ERROR

    # 3. Standard Python Built-in Non-Retryable Exceptions
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError, PermissionError, NotImplementedError)):
        return False, ErrorCategory.VALIDATION_ERROR

    # 4. Transient System / Database / Network Failures
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc).lower()
        if "locked" in msg or "busy" in msg:
            return True, ErrorCategory.STORAGE_FAILURE
        return False, ErrorCategory.STORAGE_FAILURE

    if isinstance(exc, (TimeoutError, urllib.error.URLError, ConnectionError, ConnectionResetError)):
        return True, ErrorCategory.TIMEOUT if isinstance(exc, TimeoutError) else ErrorCategory.DEPENDENCY_UNAVAILABLE

    # Default to non-retryable internal error
    return False, ErrorCategory.INTERNAL_ERROR


def execute_with_retry(
    func: Callable[[], T],
    max_attempts: Optional[int] = None,
    base_delay_ms: Optional[float] = None,
    max_delay_ms: float = 2000.0,
    retryable_exceptions: Optional[Tuple[type[Exception], ...]] = None,
    jitter: bool = True,
    operation_name: str = "operation",
    project_id: Optional[str] = None,
) -> T:
    """Executes a callable with bounded exponential backoff and jitter for retryable failures.
    Non-retryable failures (401, 403, 422, validation, auth) fail immediately.
    """
    attempts_limit = max_attempts or getattr(settings, "max_retry_attempts", 3)
    base_delay = base_delay_ms or getattr(settings, "retry_backoff_base_ms", 100.0)

    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts_limit + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            is_retryable, category = classify_failure(exc)

            if retryable_exceptions and isinstance(exc, retryable_exceptions):
                is_retryable = True

            # If not retryable or final attempt reached, fail immediately
            if not is_retryable or attempt >= attempts_limit:
                logger.warning(
                    f"Operation '{operation_name}' failed permanently on attempt {attempt}/{attempts_limit}: "
                    f"[{category.value}] {scrub_secrets(str(exc))}"
                )
                raise exc

            # Calculate bounded exponential backoff
            delay_ms = min(max_delay_ms, base_delay * (2 ** (attempt - 1)))
            if jitter:
                delay_ms = delay_ms * random.uniform(0.8, 1.2)

            delay_sec = max(0.005, delay_ms / 1000.0)

            log_operational_event(
                event="operation_retry",
                project_id=project_id,
                level=logging.WARNING,
                logger_name="beacon.resilience",
                duration_ms=round(delay_ms, 2),
                outcome=f"RETRY_ATTEMPT_{attempt}",
                error_category=category.value,
                message=f"Retrying '{operation_name}' in {delay_ms:.1f}ms (attempt {attempt}/{attempts_limit}): {scrub_secrets(str(exc))}",
                extra={
                    "attempt": attempt,
                    "max_attempts": attempts_limit,
                    "delay_ms": round(delay_ms, 2),
                    "operation": operation_name,
                },
            )

            time.sleep(delay_sec)

    # Fallback safety (should not be reached)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Operation '{operation_name}' failed after {attempts_limit} attempts.")


def with_timeout(
    func: Callable[..., T],
    timeout_seconds: Optional[float] = None,
    operation_name: str = "operation",
    *args: Any,
    **kwargs: Any,
) -> T:
    """Executes a function with a strict timeout boundary.
    Raises OperationTimeoutError if execution exceeds the deadline.
    """
    deadline = timeout_seconds or getattr(settings, "operation_timeout_seconds", 60.0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=deadline)
        except concurrent.futures.TimeoutError:
            logger.error(f"Execution of '{operation_name}' timed out after {deadline} seconds.")
            raise OperationTimeoutError(
                f"Operation '{operation_name}' timed out after {deadline:.1f} seconds.",
                details={"timeout_seconds": deadline, "operation": operation_name},
            )
