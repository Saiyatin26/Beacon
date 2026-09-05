"""BEACON V2 — Execution Security, Sandboxing & Secret Redaction.

Guarantees safe untrusted application invocation by enforcing:
1. Secret and credential masking in logs, commands, traces, and observations.
2. Sandboxed working directory and file path validation (path traversal defense via pathlib containment).
3. SSRF validation resolving hostnames and blocking cloud metadata, link-local, and unauthorized private network endpoints.
"""

import ipaddress
import logging
import os
from pathlib import Path
import re
import socket
from typing import Any, Callable, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger("beacon.execution.security")

# Sensitive key patterns for recursive credential masking
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(auth|token|secret|password|api_?key|key|cookie|credential|bearer|session|private)"
)

# Blocked SSRF metadata hostnames and IPs
_BLOCKED_METADATA_HOSTS = {
    "169.254.169.254",  # AWS/GCP/Azure instance metadata
    "169.254.170.2",    # AWS container task metadata
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
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
            return cls.redact_string(data)
        return data

    @classmethod
    def redact_string(cls, text: str) -> str:
        """Redacts embedded sensitive tokens and credentials from unstructured strings."""
        if not text:
            return text
        # Redact Bearer tokens
        text = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-_.]+", "Bearer [REDACTED]", text)
        # Redact key=value pairs with sensitive names
        text = re.sub(
            r"(?i)(password|secret|token|api_?key|auth)\s*[:=]\s*['\"]?[^'\"\s,;&]+['\"]?",
            r"\1=[REDACTED]",
            text,
        )
        return text

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
            elif "=" in arg and any(arg.lower().startswith(f"{prefix}=") for prefix in ["token", "secret", "password", "key", "auth"]):
                flag, _ = arg.split("=", 1)
                redacted.append(f"{flag}={cls.REDACTED_TEXT}")
            else:
                redacted.append(arg)
        return redacted


class SandboxedPathValidator:
    """Validates that filesystem paths reside strictly within permitted boundaries without path traversal."""

    @staticmethod
    def is_subpath(target: Path, root: Path) -> bool:
        """Robust pathlib-based containment check preventing prefix collision on sibling paths."""
        try:
            resolved_target = target.resolve()
            resolved_root = root.resolve()
            resolved_target.relative_to(resolved_root)
            return True
        except (ValueError, RuntimeError):
            return False

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
            is_permitted = any(cls.is_subpath(resolved, r) for r in resolved_roots)
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
            if not cls.is_subpath(resolved, resolved_base):
                raise PermissionError(
                    f"File path '{resolved}' escapes base directory '{resolved_base}' (path traversal detected)."
                )
        return resolved


class SSRFValidator:
    """Validates HTTP endpoints to prevent Server-Side Request Forgery against cloud metadata and private networks."""

    @classmethod
    def _inspect_ip(cls, ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address], allow_private: bool) -> None:
        """Validates a single IP against SSRF rules."""
        # 1. Block Cloud Metadata IPs
        str_ip = str(ip)
        if str_ip in _BLOCKED_METADATA_HOSTS or str_ip == "169.254.169.254" or str_ip == "169.254.170.2":
            raise PermissionError(f"SSRF Protection: Access to cloud metadata IP '{ip}' is prohibited.")

        # 2. Block Link-Local (169.254.0.0/16, fe80::/10)
        if ip.is_link_local:
            raise PermissionError(f"SSRF Protection: Access to link-local IP '{ip}' is prohibited.")

        # 3. Block Multicast, Reserved, and Unspecified (0.0.0.0, ::)
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise PermissionError(f"SSRF Protection: Access to special/reserved IP '{ip}' is prohibited.")

        # 4. Check Private / Loopback when private network access is disabled
        if not allow_private:
            if ip.is_private or ip.is_loopback:
                raise PermissionError(f"SSRF Protection: Access to private network IP '{ip}' is not permitted.")

    @classmethod
    def validate_url(
        cls,
        url: str,
        allow_private: bool = True,
        dns_resolver: Optional[Callable[[str], list[str]]] = None,
    ) -> str:
        """Validates URL scheme, hostname, resolves DNS to IP addresses, and checks against SSRF rules.
        
        allow_private allows local loopback (localhost/127.0.0.1) and RFC1918 private IPs for local testing.
        dns_resolver allows injecting a mock resolver for deterministic testing.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Must be 'http' or 'https'.")

        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"Invalid URL without hostname: '{url}'")

        if host.lower() in _BLOCKED_METADATA_HOSTS:
            raise PermissionError(f"SSRF Protection: Access to cloud metadata endpoint '{host}' is prohibited.")

        # Try parsing directly as IP address
        try:
            ip = ipaddress.ip_address(host)
            cls._inspect_ip(ip, allow_private=allow_private)
            return url
        except ValueError:
            pass

        # Hostname is a domain name: resolve to IP addresses
        resolved_ips: list[str] = []
        if dns_resolver is not None:
            resolved_ips = dns_resolver(host)
        else:
            # Standard socket resolution
            try:
                addr_info = socket.getaddrinfo(host, None)
                resolved_ips = list({info[4][0] for info in addr_info if info[4]})
            except socket.gaierror as exc:
                logger.debug(f"DNS resolution warning for host '{host}': {exc}")

        # Inspect ALL resolved IPs
        for ip_str in resolved_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                cls._inspect_ip(ip_obj, allow_private=allow_private)
            except ValueError:
                continue

        return url
