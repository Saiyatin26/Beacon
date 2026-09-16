"""BEACON V2 — Phase 10 Intelligence Security, Redaction & Multi-Tenant Isolation.

Provides deep redaction of credentials, API keys, tokens, and authorization headers,
as well as prompt injection delimiters, scope validation, and cross-application anti-leakage checks.
"""

import copy
import logging
import re
from typing import Any, Optional

from auth import Permission, User, verify_user_project_permission

logger = logging.getLogger("beacon.intelligence.security")

# Regular expressions for identifying sensitive secrets
_SECRET_KEY_PATTERNS = [
    re.compile(r"(?i)(?:api[_-]?key|secret|password|passwd|token|bearer|auth|authorization|private[_-]?key|credential|jwt|access[_-]?token)"),
]

_SECRET_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE),
    re.compile(r"(?:postgres|mysql|mongodb|redis):\/\/[^\s:]+:[^\s@]+@[^\s\/]+", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

REDACTED_PLACEHOLDER = "[REDACTED_SECRET]"


def redact_sensitive_string(text: str) -> str:
    """Redacts known secret signatures from raw strings."""
    if not isinstance(text, str):
        return text
    redacted = text
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED_PLACEHOLDER, redacted)
    return redacted


def redact_sensitive_data(payload: Any) -> Any:
    """Recursively redacts sensitive keys and secret values from arbitrary dictionaries, lists, and primitives."""
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for k, v in payload.items():
            k_str = str(k)
            # Check if key matches known secret names
            is_secret_key = any(pat.search(k_str) for pat in _SECRET_KEY_PATTERNS)
            if is_secret_key:
                cleaned[k_str] = REDACTED_PLACEHOLDER
            else:
                cleaned[k_str] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(payload, list):
        return [redact_sensitive_data(item) for item in payload]
    elif isinstance(payload, tuple):
        return tuple(redact_sensitive_data(item) for item in payload)
    elif isinstance(payload, set):
        return {redact_sensitive_data(item) for item in payload}
    elif isinstance(payload, str):
        return redact_sensitive_string(payload)
    return payload


def sanitize_prompt_input(text: str, max_chars: int = 10000) -> str:
    """Normalizes prompt text, truncates to safe bounds, and strips control characters."""
    if not text:
        return ""
    # Strip null bytes and dangerous control characters while preserving standard whitespace
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    # Redact any accidental secrets
    cleaned = redact_sensitive_string(cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + f" ... [TRUNCATED to {max_chars} chars]"
    return cleaned.strip()


def wrap_untrusted_context(title: str, content: str) -> str:
    """Wraps untrusted data (company docs, user questions) into isolated inert delimiter blocks."""
    sanitized = sanitize_prompt_input(content)
    return (
        f"<{title}_UNTRUSTED_CONTENT>\n"
        f"{sanitized}\n"
        f"</{title}_UNTRUSTED_CONTENT>"
    )


class DataIsolationChecker:
    """Validates that no cross-application or cross-project data leaks into context or outputs."""

    @staticmethod
    def verify_isolation(
        target_application_id: str,
        prohibited_application_ids: list[str],
        rendered_context_or_output: str,
    ) -> tuple[bool, list[str]]:
        """Verifies that none of the prohibited application identifiers or payloads appear in rendered context."""
        violations: list[str] = []
        for prohibited_id in prohibited_application_ids:
            if not prohibited_id or prohibited_id == target_application_id:
                continue
            if prohibited_id in rendered_context_or_output:
                violations.append(f"Contamination detected: prohibited application_id '{prohibited_id}' found in explanation context.")
        return len(violations) == 0, violations
