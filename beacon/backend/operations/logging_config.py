"""Structured Operational Logging Subsystem for BEACON.

Provides machine-readable structured operational logs with request correlation,
event tagging, timing metrics, and automatic credential/secret scrubbing.
"""

import json
import logging
import re
import contextvars
from datetime import datetime, timezone
from typing import Any, Optional

# Context variable tracking current request correlation ID across async/sync calls
current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_request_id", default="")
current_project_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_project_id", default="")

# Regex patterns for redacting sensitive credentials and tokens
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]+"),
    re.compile(r"sk-or-[a-zA-Z0-9_\-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(password|api_key|secret|token)[\"']?\s*:\s*[\"'][^\"']+[\"']", re.IGNORECASE),
    re.compile(r"mongodb\+srv:\/\/[^\s\"']+", re.IGNORECASE),
]


def scrub_secrets(text: str) -> str:
    """Replaces sensitive tokens and secrets with [REDACTED]."""
    if not isinstance(text, str):
        return text
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


class StructuredJsonFormatter(logging.Formatter):
    """Custom Formatter outputting structured JSON lines with correlation context and secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = current_request_id.get() or getattr(record, "request_id", "")
        proj_id = current_project_id.get() or getattr(record, "project_id", "")

        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub_secrets(record.getMessage()),
            "request_id": req_id,
            "project_id": proj_id,
        }

        # Include custom operational attributes if attached
        for attr in (
            "event",
            "certification_run_id",
            "dataset_id",
            "benchmark_id",
            "evaluation_mode",
            "target_variant",
            "provider",
            "duration_ms",
            "outcome",
            "error_category",
        ):
            val = getattr(record, attr, None)
            if val is not None:
                log_data[attr] = val

        if record.exc_info:
            log_data["exception"] = scrub_secrets(self.formatException(record.exc_info))

        return json.dumps(log_data)


def setup_structured_logging(level: int = logging.INFO) -> None:
    """Configures root logger or beacon logger with structured formatting."""
    root_logger = logging.getLogger("beacon")
    root_logger.setLevel(level)

    # Avoid duplicate handlers
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
    certification_run_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    evaluation_mode: Optional[str] = None,
    target_variant: Optional[str] = None,
    provider: Optional[str] = None,
    duration_ms: Optional[float] = None,
    outcome: Optional[str] = None,
    error_category: Optional[str] = None,
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emits a structured operational log entry with standardized fields."""
    logger = logging.getLogger(logger_name)
    extra_fields = {
        "event": event,
        "request_id": current_request_id.get(),
        "project_id": project_id or current_project_id.get(),
        "certification_run_id": certification_run_id,
        "dataset_id": dataset_id,
        "benchmark_id": benchmark_id,
        "evaluation_mode": evaluation_mode,
        "target_variant": target_variant,
        "provider": provider,
        "duration_ms": duration_ms,
        "outcome": outcome,
        "error_category": error_category,
    }
    extra_fields.update(extra)

    msg = message or f"Operational event '{event}' occurred"
    logger.log(level, msg, extra=extra_fields)
