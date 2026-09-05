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

# Sensitive key names and word boundaries (avoids over-redacting words like monkey, keyboard, keypad)
_SENSITIVE_KEY_NAMES = {
    "auth", "authorization", "token", "access_token", "refresh_token", "secret",
    "client_secret", "private_key", "password", "passwd", "database_password",
    "db_password", "db_pass", "api_key", "apikey", "cookie", "set_cookie",
    "session", "credential", "bearer", "proxy_authorization"
}

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)^(auth|authorization|token|access_token|refresh_token|secret|client_secret|private_key|password|passwd|database_password|db_password|db_pass|api_?key|apikey|cookie|set_cookie|session|credential|bearer|proxy_authorization)$"
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
    def is_sensitive_key(cls, key: Any) -> bool:
        """Determines if a dictionary key represents sensitive credentials using normalized word matching."""
        s = str(key).lower().strip()
        if _SENSITIVE_KEY_PATTERN.match(s):
            return True
        s_norm = re.sub(r"[._\-/\\]+", "_", s)
        s_clean = re.sub(r"[._\-/\\]+", "", s)
        for sens in _SENSITIVE_KEY_NAMES:
            sens_clean = re.sub(r"[._\-/\\]+", "", sens)
            if sens in s_norm or sens_clean in s_clean:
                return True
        # Split on non-alphanumeric separators (e.g. user.password, app_secret, api-key)
        parts = [p for p in re.split(r"[._\-/\\]+", s) if p]
        if any(p in _SENSITIVE_KEY_NAMES for p in parts):
            return True
        return False

    @classmethod
    def redact(cls, data: Any) -> Any:
        """Recursively sanitizes dictionary, list, and string structures."""
        if isinstance(data, dict):
            redacted_dict: dict[str, Any] = {}
            for k, v in data.items():
                if cls.is_sensitive_key(k):
                    redacted_dict[k] = cls.REDACTED_TEXT
                else:
                    redacted_dict[k] = cls.redact(v)
            return redacted_dict
        elif isinstance(data, list):
            return [cls.redact(item) for item in data]
        elif isinstance(data, tuple):
            return tuple(cls.redact(item) for item in data)
        elif isinstance(data, str):
            return cls.redact_string(data)
        return data

    @classmethod
    def redact_string(cls, text: str) -> str:
        """Redacts embedded sensitive tokens, HTTP headers, and credentials from unstructured text."""
        if not text:
            return text

        # 1. Redact Bearer tokens
        text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9\-_.]+", "Bearer [REDACTED]", text)

        # 2. Redact HTTP-style authorization headers (case-insensitive with various separators)
        text = re.sub(
            r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?([^\r\n,;]+)",
            r"\1: [REDACTED]",
            text,
        )
        text = re.sub(
            r"(?i)\b(x-api-key|api-key|apikey)\s*[:=]\s*([^\r\n,;]+)",
            r"\1: [REDACTED]",
            text,
        )
        text = re.sub(
            r"(?i)\b(cookie|set-cookie)\s*[:=]\s*([^\r\n,;]+)",
            r"\1: [REDACTED]",
            text,
        )

        # 3. Redact key-value pairs with sensitive names (passwords, tokens, keys)
        text = re.sub(
            r"(?i)\b([A-Za-z0-9_.-]*(?:password|passwd|secret|token|access_token|refresh_token|api_?key|apikey|credential|private_key|client_secret|database_password|db_password|db_pass)[A-Za-z0-9_.-]*)\b\s*([:=])\s*['\"]?([^'\"\s,;&\r\n]+)['\"]?",
            r"\1\2[REDACTED]",
            text,
        )

        # 4. Redact URL query parameters
        text = re.sub(
            r"(?i)([?&](?:api_?key|token|access_token|secret|password|auth|passwd)=)[^&\s]+",
            r"\1[REDACTED]",
            text,
        )

        return text

    @classmethod
    def redact_command(cls, command_args: list[str]) -> list[str]:
        """Redacts sensitive values in CLI argument lists (e.g. --password secret -> --password [REDACTED], -e KEY=secret -> -e KEY=[REDACTED])."""
        redacted = []
        mask_next = False
        for arg in command_args:
            if mask_next:
                redacted.append(cls.REDACTED_TEXT)
                mask_next = False
                continue

            if any(arg.lower().startswith(f"--{prefix}=") for prefix in ["token", "secret", "password", "key", "auth", "passwd"]):
                flag, _ = arg.split("=", 1)
                redacted.append(f"{flag}={cls.REDACTED_TEXT}")
            elif arg.lower() in ["--token", "--secret", "--password", "--key", "--auth", "-p"]:
                redacted.append(arg)
                mask_next = True
            elif "=" in arg and any(arg.lower().startswith(f"{prefix}=") for prefix in ["token", "secret", "password", "key", "auth", "passwd"]):
                flag, _ = arg.split("=", 1)
                redacted.append(f"{flag}={cls.REDACTED_TEXT}")
            elif arg.startswith("-e") and "=" in arg:
                var_name, _ = arg.split("=", 1)
                redacted.append(f"{var_name}=[REDACTED]")
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
        """Resolves target directory and validates against permitted directory boundaries.
        
        Defaults allowed_roots to settings.get_sandbox_root() if omitted.
        Fails closed if target_dir does not exist, is not a directory, or resolves outside allowed roots.
        """
        resolved = Path(target_dir).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Configured working directory does not exist: '{resolved}'")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Configured working directory is not a directory: '{resolved}'")

        if allowed_roots is None:
            try:
                from common.config import settings
                sandbox_root = settings.get_sandbox_root()
                if not sandbox_root or not Path(sandbox_root).exists():
                    raise PermissionError(f"Authoritative sandbox root is invalid or inaccessible: '{sandbox_root}'")
                allowed_roots = [sandbox_root]
            except Exception as exc:
                raise PermissionError(f"Failed to load authoritative sandbox root configuration: {exc}") from exc

        resolved_roots = [Path(r).resolve() for r in allowed_roots if r]
        if not resolved_roots:
            raise PermissionError("No valid allowed roots provided for sandbox containment check.")

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
    def validate_and_resolve_destination(
        cls,
        url: str,
        allow_private: bool = True,
        dns_resolver: Optional[Callable[[str], list[str]]] = None,
    ) -> tuple[str, str, str, int]:
        """Validates URL and resolves destination host to safe IP addresses.
        
        Returns:
            (validated_url, primary_validated_ip, original_host, port)
        Fails closed on resolution error or SSRF policy violation.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Must be 'http' or 'https'.")

        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"Invalid URL without hostname: '{url}'")

        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if host.lower() in _BLOCKED_METADATA_HOSTS:
            raise PermissionError(f"SSRF Protection: Access to cloud metadata endpoint '{host}' is prohibited.")

        # Check if hostname is directly an IP literal
        try:
            ip = ipaddress.ip_address(host)
            cls._inspect_ip(ip, allow_private=allow_private)
            return url, str(ip), host, port
        except ValueError:
            pass

        # Hostname is a domain name: resolve to IP addresses
        resolved_ips: list[str] = []
        if dns_resolver is not None:
            try:
                resolved_ips = dns_resolver(host)
            except Exception as exc:
                raise PermissionError(
                    f"Unable to resolve hostname '{host}'; HTTP request blocked by SSRF policy."
                ) from exc
        else:
            try:
                addr_info = socket.getaddrinfo(host, None)
                resolved_ips = list({info[4][0] for info in addr_info if info[4]})
            except (socket.gaierror, socket.herror, socket.timeout, OSError) as exc:
                raise PermissionError(
                    f"Unable to resolve hostname '{host}'; HTTP request blocked by SSRF policy."
                ) from exc
            except Exception as exc:
                raise PermissionError(
                    f"Unable to resolve hostname '{host}'; HTTP request blocked by SSRF policy."
                ) from exc

        # Empty DNS results MUST fail closed
        if not resolved_ips:
            raise PermissionError(
                f"Unable to resolve hostname '{host}'; HTTP request blocked by SSRF policy."
            )

        # Inspect ALL resolved IPs: if ANY IP violates policy, REJECT
        for ip_str in resolved_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                cls._inspect_ip(ip_obj, allow_private=allow_private)
            except ValueError:
                raise PermissionError(
                    f"Invalid resolved IP address '{ip_str}' for host '{host}'; HTTP request blocked by SSRF policy."
                )

        return url, resolved_ips[0], host, port

    @classmethod
    def validate_url(
        cls,
        url: str,
        allow_private: bool = True,
        dns_resolver: Optional[Callable[[str], list[str]]] = None,
    ) -> str:
        """Validates URL scheme, hostname, resolves DNS to IP addresses, and checks against SSRF rules."""
        validated_url, _, _, _ = cls.validate_and_resolve_destination(
            url, allow_private=allow_private, dns_resolver=dns_resolver
        )
        return validated_url
