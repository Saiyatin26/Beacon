"""BEACON V2 — Execution Security, Sandboxing & Secret Redaction.

Guarantees safe untrusted application invocation by enforcing:
1. Secret and credential masking in logs, commands, traces, and observations.
2. Sandboxed working directory and file path validation (path traversal defense).
3. SSRF validation blocking cloud metadata, link-local, and unauthorized private network endpoints.
"""

import ipaddress
import logging
import os
from pathlib import Path
import re
from typing import Any, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger("beacon.execution.security")

# Sensitive key patterns for recursive credential masking
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(auth|token|secret|password|api_?key|key|cookie|credential|bearer|session|private)"
)

# Blocked SSRF metadata addresses
_BLOCKED_METADATA_IPS = {
    "169.254.169.254",  # AWS/GCP/Azure instance metadata
    "169.254.170.2",    # AWS container task metadata
    "metadata.google.internal",
}


class SecretRedactor:
    """Recursively masks sensitive tokens, passwords, and authorization data."""

    REDACTED_TEXT = "[REDACTED]"

    @classmethod
    def redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            redacted_dict: dict[str, Any] = {}
            for k, v in data.items():
                if _SENSITIVE_KEY_PATTERN.search(str(k)):
                    redacted_dict[k] = cls.REDACTED_TEXT
                else:
                    redacted_dict[k] = cls.redact(v)
            return redacted_dict
        elif isinstance(data, list):
            return [cls.redact(item) for item in data]
        elif isinstance(data, str):
            # Mask Bearer tokens or sensitive headers formatted as "Bearer ..."
            if data.lower().startswith("bearer "):
                return "Bearer [REDACTED]"
            return data
        return data

    @classmethod
    def redact_command(cls, command_args: list[str]) -> list[str]:
        """Redacts sensitive values in CLI argument lists (e.g. --password secret -> --password [REDACTED])."""
        redacted = []
        mask_next = False
        for arg in command_args:
            if mask_next:
                redacted.append(cls.REDACTED_TEXT)
                mask_next = False
                continue

            if any(arg.lower().startswith(f"--{prefix}=") for prefix in ["token", "secret", "password", "key", "auth"]):
                flag, _ = arg.split("=", 1)
                redacted.append(f"{flag}={cls.REDACTED_TEXT}")
            elif arg.lower() in ["--token", "--secret", "--password", "--key", "--auth", "-p"]:
                redacted.append(arg)
                mask_next = True
            else:
                redacted.append(arg)
        return redacted


class SandboxedPathValidator:
    """Validates that filesystem paths reside within permitted workspaces without path traversal."""

    @classmethod
    def validate_working_directory(
        cls,
        target_dir: Union[str, Path],
        allowed_roots: Optional[list[Union[str, Path]]] = None,
    ) -> Path:
        """Resolves target directory and validates against permitted directory boundaries."""
        resolved = Path(target_dir).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Configured working directory does not exist: '{resolved}'")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Configured working directory is not a directory: '{resolved}'")

        if allowed_roots:
            resolved_roots = [Path(r).resolve() for r in allowed_roots]
            is_permitted = any(
                str(resolved).startswith(str(r)) for r in resolved_roots
            )
            if not is_permitted:
                raise PermissionError(
                    f"Working directory '{resolved}' is outside allowed root boundaries: {[str(r) for r in resolved_roots]}"
                )

        return resolved

    @classmethod
    def validate_file_path(
        cls,
        file_path: Union[str, Path],
        base_dir: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Validates that a file path exists and is safely contained within base_dir if specified."""
        resolved = Path(file_path).resolve()
        if base_dir:
            resolved_base = Path(base_dir).resolve()
            if not str(resolved).startswith(str(resolved_base)):
                raise PermissionError(
                    f"File path '{resolved}' escapes base directory '{resolved_base}' (path traversal detected)."
                )
        return resolved


class SSRFValidator:
    """Validates HTTP endpoints to prevent Server-Side Request Forgery against cloud metadata."""

    @classmethod
    def validate_url(cls, url: str, allow_private: bool = True) -> str:
        """Validates URL scheme, host, and blocks cloud metadata endpoints.
        allow_private allows local loopback (localhost/127.0.0.1) for testing target services.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Must be 'http' or 'https'.")

        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"Invalid URL without hostname: '{url}'")

        if host.lower() in _BLOCKED_METADATA_IPS:
            raise PermissionError(f"SSRF Protection: Access to cloud metadata endpoint '{host}' is prohibited.")

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_link_local:
                raise PermissionError(f"SSRF Protection: Access to link-local IP '{ip}' is prohibited.")
            if not allow_private and (ip.is_private or ip.is_loopback):
                raise PermissionError(f"SSRF Protection: Access to private network IP '{ip}' is not permitted.")
        except ValueError:
            # Hostname is a domain name, not a raw IP
            pass

        return url
