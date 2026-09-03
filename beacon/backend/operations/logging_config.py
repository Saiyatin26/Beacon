"""Structured Operational Logging Subsystem for BEACON.

Provides machine-readable structured operational logs with request correlation,
event tagging, timing metrics, automatic credential/secret scrubbing, and log injection protection.
"""

import json
import logging
import re
import contextvars
import time
from contextlib import contextmanager
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
            "operation",
            "phase",
            "step",
            "records",
            "cases",
            "oracles",
            "regressions",
            "matching",
            "backend",
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


class HumanReadableConsoleFilter(logging.Filter):
    """Keeps the demonstration console focused on BEACON execution and HTTP events."""

    def filter(self, record: logging.LogRecord) -> bool:
        return (
            record.name.startswith("beacon.execution")
            or record.name == "beacon.operations.http"
            or record.name == "beacon.lifecycle"
        )


class BeaconConsoleFormatter(logging.Formatter):
    """Formats operational events as a compact, human-readable execution monitor."""

    CHECK = "\N{CHECK MARK}"
    CROSS = "\N{BALLOT X}"

    @staticmethod
    def _value(record: logging.LogRecord, name: str, default: Any = "") -> Any:
        return getattr(record, name, default)

    @staticmethod
    def _status(outcome: str, level: int) -> str:
        normalized = (outcome or "").upper()
        if normalized in {"FAILED", "FAIL", "ABORTED", "NOT_CERTIFIED", "REGRESSION"} or level >= logging.ERROR:
            return f"FAILED {BeaconConsoleFormatter.CROSS}"
        if normalized in {"COMPLETE", "COMPLETED", "COMMITTED", "CERTIFIED", "READY", "SUCCESS", "HTTP_200"}:
            return f"COMPLETED {BeaconConsoleFormatter.CHECK}"
        return "STARTED"

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if record.name == "beacon.operations.http":
            method = self._value(record, "method", "?")
            path = self._value(record, "path", "?")
            status_code = self._value(record, "status_code", "?")
            duration = self._value(record, "duration_ms", None)
            status_text = "OK" if str(status_code).startswith("2") else "ERROR"
            timing = f" ({duration:.2f} ms)" if isinstance(duration, (int, float)) else ""
            return f"[{timestamp}] [HTTP] {method} {path} ..... {status_code} {status_text}{timing}"

        if record.name == "beacon.lifecycle":
            state = self._value(record, "event", "").replace("job_state_", "").replace("_", " ").upper()
            marker = f" {self.CHECK}" if state == "COMPLETED" else (f" {self.CROSS}" if state in {"FAILED", "CANCELLED"} else "")
            return f"[{timestamp}] JOB LIFECYCLE | {state}{marker}"

        event = self._value(record, "event", "")
        operation = self._value(record, "operation", "OPERATION")
        step = self._value(record, "step", "")
        outcome = self._value(record, "outcome", "")
        run_id = self._value(record, "certification_run_id", "")
        message = scrub_secrets(record.getMessage())

        if event in {"certification_started", "custom_certification_started", "preflight_started"}:
            lines = ["", "=" * 60, "                 BEACON EXECUTION MONITOR", "=" * 60]
            lines.append(f"[{timestamp}] REQUEST RECEIVED")
            lines.append(f"Operation : {operation}")
            if run_id:
                lines.append(f"Run ID    : {run_id}")
            return "\n".join(lines)

        if event in {"certification_completed", "custom_certification_completed"}:
            status = outcome or "COMPLETE"
            marker = self.CHECK if status in {"CERTIFIED", "CERTIFIED_WITH_WARNINGS"} else self.CROSS
            duration = self._value(record, "duration_ms", None)
            duration_text = f" | duration={duration:.2f}ms" if isinstance(duration, (int, float)) else ""
            return (
                f"[{timestamp}] FINAL RESULT    : {marker} {status}\n"
                f"[{timestamp}] OPERATION COMPLETE{duration_text}"
            )

        if event in {"execution_step_started", "execution_step_completed", "execution_step_failed"}:
            state = self._status(outcome, record.levelno)
            duration = self._value(record, "duration_ms", None)
            duration_text = f" | Duration: {duration:.2f} ms" if isinstance(duration, (int, float)) else ""
            return f"[{timestamp}] {operation} | {step} | [{state}]{duration_text}"

        if event == "certification_policy_decision":
            return f"[{timestamp}] CERTIFICATION DECISION | {outcome} | {message}"

        if event == "certification_persistence_started":
            return f"[{timestamp}] DATABASE PERSISTENCE | [STARTED] | backend={self._value(record, 'backend', 'unknown')}"
        if event == "certification_persistence_completed":
            return f"[{timestamp}] DATABASE PERSISTENCE | [COMPLETED {self.CHECK}] | backend={self._value(record, 'backend', 'unknown')}"
        if event == "certification_persistence_failed":
            return f"[{timestamp}] DATABASE PERSISTENCE | [FAILED {self.CROSS}] | transaction rolled back"

        return f"[{timestamp}] {message}"


def setup_structured_logging(level: Optional[int] = None) -> None:
    """Configures JSON debug output and a focused human-readable console output."""
    log_level_name = getattr(settings, "log_level", "INFO").upper()
    resolved_level = level if level is not None else getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger("beacon")
    root_logger.setLevel(resolved_level)

    # Avoid duplicate structured handlers
    if not any(isinstance(h.formatter, StructuredJsonFormatter) for h in root_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        root_logger.addHandler(handler)
    if not any(getattr(h, "_beacon_human_console", False) for h in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(BeaconConsoleFormatter())
        console_handler.addFilter(HumanReadableConsoleFilter())
        console_handler._beacon_human_console = True
        root_logger.addHandler(console_handler)


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


@contextmanager
def execution_step(
    operation: str,
    step: str,
    *,
    phase: Optional[str] = None,
    logger_name: str = "beacon.execution",
    **fields: Any,
):
    """Logs a timed execution step without exposing payloads or changing control flow."""
    started = time.perf_counter()
    context = {"operation": operation, "step": step, **fields}
    if phase:
        context["phase"] = phase
    log_operational_event(
        event="execution_step_started",
        logger_name=logger_name,
        message=f"[{operation}] [{step}] START",
        **context,
    )
    try:
        yield
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        log_operational_event(
            event="execution_step_failed",
            level=logging.ERROR,
            logger_name=logger_name,
            duration_ms=duration_ms,
            outcome="FAILED",
            safe_error=str(exc),
            message=f"[{operation}] [{step}] ERROR | duration={duration_ms:.2f}ms",
            **context,
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        log_operational_event(
            event="execution_step_completed",
            logger_name=logger_name,
            duration_ms=duration_ms,
            outcome="COMPLETE",
            message=f"[{operation}] [{step}] COMPLETE | duration={duration_ms:.2f}ms",
            **context,
        )


