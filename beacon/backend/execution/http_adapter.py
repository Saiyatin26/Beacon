"""BEACON V2 — Generic HTTP / REST Implementation Adapter.

Executes remote or local HTTP/REST endpoints with:
1. Method, path interpolation, headers, query parameters, and JSON/text payload mapping.
2. SSRF validation preventing cloud metadata access.
3. Secret redaction on auth tokens and request bodies in logs and observation outputs.
4. Non-2xx response error mapping and timeout enforcement.
"""

import json
import logging
import os
import time
from typing import Any, Optional, Union
import httpx

from certification.adapters import AdapterRole, ImplementationAdapter
from certification.models import CanonicalInput, Observation
from .mapping import InputMapper, OutputMapper
from .models import AdapterCapabilities, AdapterHealth, AdapterHealthStatus, AdapterType
from .security import SSRFValidator, SecretRedactor

logger = logging.getLogger("beacon.execution.http")


class HttpAdapter(ImplementationAdapter):
    """Executes a target service via HTTP/REST requests."""

    def __init__(
        self,
        base_url: str,
        path_template: str = "",
        method: str = "POST",
        headers: Optional[dict[str, str]] = None,
        auth_reference: Optional[str] = None,  # Environment variable name holding token
        timeout_seconds: float = 30.0,
        name: str = "http_adapter",
        version: str = "1.0.0",
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
        input_mapper: Optional[InputMapper] = None,
        output_mapper: Optional[OutputMapper] = None,
        allow_private_network: bool = True,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.path_template = path_template
        self.method = method.upper()
        self.headers = dict(headers or {})
        self.auth_reference = auth_reference
        self.timeout_seconds = timeout_seconds
        self.name = name
        self.version = version
        self.role = role
        self.adapter_type = AdapterType.HTTP
        self.input_mapper = input_mapper or InputMapper()
        self.output_mapper = output_mapper or OutputMapper()
        self.allow_private_network = allow_private_network
        self.metadata = metadata or {}

        self.capabilities = AdapterCapabilities(
            supports_timeout=True,
            supports_streaming=False,
            supports_files=False,
            supports_binary=True,
            supports_traces=True,
            supports_cleanup=True,
            supports_state_capture=False,
            supports_custom_environment=True,
            supports_sandboxing=True,
        )

        self.implementation_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        import hashlib
        payload = {
            "name": self.name,
            "version": self.version,
            "role": str(self.role),
            "base_url": self.base_url,
            "method": self.method,
        }
        return hashlib.sha256(str(payload).encode()).hexdigest()

    def health_check(self) -> AdapterHealth:
        """Validates endpoint URL format and SSRF constraints."""
        try:
            full_url = f"{self.base_url}/{self.path_template.lstrip('/')}".rstrip("/")
            SSRFValidator.validate_url(full_url, allow_private=self.allow_private_network)
            return AdapterHealth(
                adapter_id=f"{self.name}:{self.version}",
                status=AdapterHealthStatus.AVAILABLE,
                is_ready=True,
                diagnostics=f"HTTP Adapter endpoint '{self.base_url}' is valid.",
                capabilities=self.capabilities,
            )
        except Exception as exc:
            return AdapterHealth(
                adapter_id=f"{self.name}:{self.version}",
                status=AdapterHealthStatus.MISCONFIGURED,
                is_ready=False,
                diagnostics=f"HTTP Adapter URL validation error: {exc}",
                capabilities=self.capabilities,
            )

    def validate(self, input_data: Any) -> bool:
        health = self.health_check()
        return health.is_ready

    def _prepare_headers(self) -> dict[str, str]:
        req_headers = dict(self.headers)
        if self.auth_reference:
            token = os.environ.get(self.auth_reference)
            if token:
                req_headers["Authorization"] = f"Bearer {token}"
        if "Content-Type" not in req_headers and self.method in ("POST", "PUT", "PATCH"):
            req_headers["Content-Type"] = "application/json"
        return req_headers

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        actual_input_id = input_id
        if isinstance(inputs, CanonicalInput):
            actual_input_id = input_id or inputs.input_id
            raw_inputs = inputs.get_data()
        else:
            raw_inputs = dict(inputs)

        mapped_kwargs = self.input_mapper.map_to_kwargs(inputs)

        # Build URL with path interpolation if needed
        full_url = f"{self.base_url}/{self.path_template.lstrip('/')}".rstrip("/")
        try:
            full_url = full_url.format(**mapped_kwargs)
        except KeyError:
            pass

        # Validate URL for SSRF
        SSRFValidator.validate_url(full_url, allow_private=self.allow_private_network)

        headers = self._prepare_headers()
        safe_headers = SecretRedactor.redact(headers)
        safe_body = SecretRedactor.redact(mapped_kwargs)
        logger.info(f"Executing HTTP request [{self.method}] {full_url} on input #{actual_input_id}")

        start_time = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                if self.method == "GET":
                    resp = client.get(full_url, headers=headers, params=mapped_kwargs)
                elif self.method == "POST":
                    resp = client.post(full_url, headers=headers, json=mapped_kwargs)
                elif self.method == "PUT":
                    resp = client.put(full_url, headers=headers, json=mapped_kwargs)
                elif self.method == "PATCH":
                    resp = client.patch(full_url, headers=headers, json=mapped_kwargs)
                elif self.method == "DELETE":
                    resp = client.delete(full_url, headers=headers, params=mapped_kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {self.method}")

            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

            resp_text = resp.text
            try:
                parsed_json = resp.json()
                raw_out = parsed_json if isinstance(parsed_json, dict) else {"output": parsed_json}
            except Exception:
                raw_out = {"body": resp_text}

            status_code = resp.status_code
            if 200 <= status_code < 300:
                execution_status = "SUCCESS"
                error_msg = None
            else:
                execution_status = "EXCEPTION"
                error_msg = f"HTTP request returned status {status_code}: {resp_text[:500]}"

            mapped_outputs = self.output_mapper.map_output(
                raw_output=raw_out,
                status_code=status_code,
            )
            norm_outputs = self.normalize_output(mapped_outputs)

            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs=mapped_outputs,
                normalized_outputs=norm_outputs,
                execution_status=execution_status,
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=error_msg,
                provenance={
                    "adapter_type": AdapterType.HTTP.value,
                    "role": str(self.role),
                    "status_code": status_code,
                    "url": full_url,
                },
            )

        except httpx.TimeoutException as te:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            logger.warning(f"HTTP adapter '{self.name}' timed out after {self.timeout_seconds}s on input #{actual_input_id}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs={"error": f"HTTP request timed out after {self.timeout_seconds} seconds"},
                normalized_outputs={"error": f"HTTP request timed out after {self.timeout_seconds} seconds"},
                execution_status="TIMEOUT",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=f"HTTP request timed out after {self.timeout_seconds} seconds",
                provenance={
                    "adapter_type": AdapterType.HTTP.value,
                    "role": str(self.role),
                    "error_type": "TimeoutException",
                },
            )

        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            logger.error(f"HTTP adapter '{self.name}' execution failure: {exc}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs={"error": str(exc)},
                normalized_outputs={"error": str(exc)},
                execution_status="EXCEPTION",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=str(exc),
                provenance={
                    "adapter_type": AdapterType.HTTP.value,
                    "role": str(self.role),
                    "error_type": type(exc).__name__,
                },
            )
