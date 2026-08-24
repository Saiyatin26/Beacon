"""Structured Operational Logging Subsystem for BEACON.

Provides machine-readable structured operational logs with request correlation,
event tagging, timing metrics, automatic credential/secret scrubbing, and log injection protection.
"""

import json
import logging
import re
import contextvars
from datetime import datetime, timezone
from typing import Any, Optional

from common.config import settings

# Context variables tracking request correlation across async/sync calls
current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_request_id", default="")
current_project_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_project_id", default="")
current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_id", default="")

# Comprehensive regex patterns for scrubbing sensitive credentials, tokens, secrets, and connection URIs
SECRET_PATTERNS = [
    # Raw 3-part dot-separated JWT tokens
    re.compile(r"eyJ[a-zA-Z0-9_\-]{8,}\.eyJ[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]+"),
    # Bearer authorization tokens
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+", re.IGNORECASE),
    # Common provider API keys
    re.compile(r"(sk-ant-|sk-or-|sk-proj-|key-|secret-)[a-zA-Z0-9_\-]+", re.IGNORECASE),
    # Key-value secret assignments in JSON / query params / config strings
    re.compile(r"(password|api_key|jwt_secret|signing_secret|secret_key|client_secret|access_token|refresh_token)[\"']?\s*[:=]\s*[\"']?[^\"'\s,;}{]+[\"']?", re.IGNORECASE),
    # Database connection URIs
    re.compile(r"(mongodb(\+srv)?|postgres(ql)?|mysql|redis):\/\/[^\s\"']+", re.IGNORECASE),
    # Authorization header patterns
    re.compile(r"authorization[\"']?\s*:\s*[\"'][^\"']+[\"']", re.IGNORECASE),
]

# Control character pattern for neutralizing log-injection attempts
CONTROL_CHAR_PATTERN = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_log_string(val: Any) -> str:
    """Neutralizes control characters and newlines to prevent log injection."""
    if not isinstance(val, str):
        val = str(val)
    return CONTROL_CHAR_PATTERN.sub(" ", val).strip()


def scrub_secrets(text: Any) -> str:
    """Replaces sensitive tokens, keys, passwords, and secrets with [REDACTED_SECRET]."""
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitize_log_string(sanitized)


class StructuredJsonFormatter(logging.Formatter):
    """Custom Formatter outputting structured JSON lines with correlation context,
    secret scrubbing, and log-injection protection.
    """

    def format(self, record: logging.LogRecord) -> str:
        req_id = current_request_id.get() or getattr(record, "request_id", "")
        proj_id = current_project_id.get() or getattr(record, "project_id", "")
        usr_id = current_user_id.get() or getattr(record, "user_id", "")

        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": sanitize_log_string(record.name),
            "message": scrub_secrets(record.getMessage()),
            "request_id": sanitize_log_string(req_id) if req_id else "",
            "project_id": sanitize_log_string(proj_id) if proj_id else "",
            "user_id": sanitize_log_string(usr_id) if usr_id else "",
        }

        # Include standardized operational attributes if attached
        for attr in (
            "event",
            "module",
            "certification_run_id",
            "dataset_id",
            "benchmark_id",
            "evaluation_mode",
            "target_variant",
            "provider",
            "duration_ms",
            "outcome",
            "error_category",
            "safe_error",
            "status_code",
            "method",
            "path",
        ):
            val = getattr(record, attr, None)
            if val is not None:
                if isinstance(val, str):
                    log_data[attr] = scrub_secrets(val)
                elif isinstance(val, (int, float, bool)):
                    log_data[attr] = val
                else:
                    log_data[attr] = scrub_secrets(str(val))

        if record.exc_info:
            log_data["exception"] = scrub_secrets(self.formatException(record.exc_info))

        return json.dumps(log_data)


def setup_structured_logging(level: Optional[int] = None) -> None:
    """Configures root beacon logger with structured JSON formatting and configured level."""
    log_level_name = getattr(settings, "log_level", "INFO").upper()
    resolved_level = level if level is not None else getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger("beacon")
    root_logger.setLevel(resolved_level)

    # Avoid duplicate structured handlers
    if not any(isinstance(h.formatter, StructuredJsonFormatter) for h in root_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        root_logger.addHandler(handler)


def get_logger(name: str = "beacon.operations") -> logging.Logger:
    """Returns a named logger under the beacon namespace."""
    return logging.getLogger(name)


def log_operational_event(
    event: str,
    level: int = logging.INFO,
    logger_name: str = "beacon.operations",
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    certification_run_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    evaluation_mode: Optional[str] = None,
    target_variant: Optional[str] = None,
    provider: Optional[str] = None,
    duration_ms: Optional[float] = None,
    outcome: Optional[str] = None,
    error_category: Optional[str] = None,
    safe_error: Optional[str] = None,
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emits a structured operational log entry with standardized fields and automatic redaction.
    Guaranteed non-blocking: never raises exceptions to caller.
    """
    try:
        log_obj = logging.getLogger(logger_name)
        extra_fields = {
            "event": sanitize_log_string(event),
            "request_id": current_request_id.get(),
            "project_id": project_id or current_project_id.get(),
            "user_id": user_id or current_user_id.get(),
            "certification_run_id": certification_run_id,
            "dataset_id": dataset_id,
            "benchmark_id": benchmark_id,
            "evaluation_mode": evaluation_mode,
            "target_variant": target_variant,
            "provider": provider,
            "duration_ms": duration_ms,
            "outcome": outcome,
            "error_category": error_category,
            "safe_error": scrub_secrets(safe_error) if safe_error else None,
        }
        for k, v in extra.items():
            extra_fields[k] = scrub_secrets(v) if isinstance(v, str) else v

        msg = scrub_secrets(message or f"Operational event '{event}' occurred")
        log_obj.log(level, msg, extra=extra_fields)
    except Exception:
        # Non-blocking: fail safely without interrupting business operations
        pass


