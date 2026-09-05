"""BEACON V2 — Container Implementation Adapter.

Executes applications inside isolated container runtimes (Docker, Podman, OCI) with:
1. Capability-based detection: reports structured UNAVAILABLE health diagnostics when Docker is absent without failing BEACON startup.
2. Supported container resource bounds enforcement (CPU quota, memory limits, PIDs limits).
3. Secure secret references without embedding plaintext credentials in ApplicationSpec.
4. Guaranteed non-leaking container command logging and execution lifecycle cleanup.
"""

import logging
import os
import shutil
from typing import Any, Optional, Union

from certification.adapters import AdapterRole, ImplementationAdapter
from certification.models import CanonicalInput, Observation
from .models import AdapterCapabilities, AdapterHealth, AdapterHealthStatus, AdapterType
from .security import SecretRedactor

logger = logging.getLogger("beacon.execution.container")

# Supported container CLI resource flags
_SUPPORTED_RESOURCE_LIMITS = {
    "cpus": "--cpus",
    "memory": "--memory",
    "pids_limit": "--pids-limit",
    "cpu_shares": "--cpu-shares",
    "memory_swap": "--memory-swap",
}


class ContainerAdapter(ImplementationAdapter):
    """Executes target implementations inside container environments."""

    def __init__(
        self,
        image: str,
        command: Optional[list[str]] = None,
        container_engine: str = "docker",
        entrypoint: Optional[str] = None,
        working_dir: Optional[str] = None,
        environment_variables: Optional[dict[str, str]] = None,
        secret_references: Optional[dict[str, str]] = None,  # container_var -> host_env_var_name
        resource_limits: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 60.0,
        name: str = "container_adapter",
        version: str = "1.0.0",
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.image = image
        self.command = command or []
        self.container_engine = container_engine
        self.entrypoint = entrypoint
        self.working_dir = working_dir
        self.environment_variables = dict(environment_variables or {})
        self.secret_references = dict(secret_references or {})
        self.resource_limits = dict(resource_limits or {})
        self.timeout_seconds = timeout_seconds
        self.name = name
        self.version = version
        self.role = role
        self.adapter_type = AdapterType.CONTAINER
        self.metadata = metadata or {}

        # Validate resource limits support
        self.unsupported_limits = [
            k for k in self.resource_limits.keys() if k not in _SUPPORTED_RESOURCE_LIMITS
        ]
        if self.unsupported_limits:
            logger.info(
                f"ContainerAdapter '{self.name}' notes unsupported resource limit keys: {self.unsupported_limits}. "
                f"Supported keys: {list(_SUPPORTED_RESOURCE_LIMITS.keys())}"
            )

        self.capabilities = AdapterCapabilities(
            supports_timeout=True,
            supports_streaming=False,
            supports_files=True,
            supports_binary=True,
            supports_traces=False,
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
            "image": self.image,
            "command": self.command,
            "resource_limits": self.resource_limits,
        }
        return hashlib.sha256(str(payload).encode()).hexdigest()

    def health_check(self) -> AdapterHealth:
        """Capability-based check detecting container engine presence."""
        engine_path = shutil.which(self.container_engine)
        if not engine_path:
            return AdapterHealth(
                adapter_id=f"{self.name}:{self.version}",
                status=AdapterHealthStatus.UNAVAILABLE,
                is_ready=False,
                diagnostics=f"Container engine '{self.container_engine}' was not found in system PATH. Docker/container execution is currently unavailable.",
                capabilities=self.capabilities,
                details={
                    "image": self.image,
                    "engine": self.container_engine,
                    "supported_limits": list(_SUPPORTED_RESOURCE_LIMITS.keys()),
                    "configured_limits": self.resource_limits,
                },
            )

        return AdapterHealth(
            adapter_id=f"{self.name}:{self.version}",
            status=AdapterHealthStatus.AVAILABLE,
            is_ready=True,
            diagnostics=f"Container engine '{self.container_engine}' is present at '{engine_path}'.",
            capabilities=self.capabilities,
            details={
                "image": self.image,
                "engine_path": engine_path,
                "supported_limits": list(_SUPPORTED_RESOURCE_LIMITS.keys()),
                "configured_limits": self.resource_limits,
                "unsupported_limits": self.unsupported_limits,
            },
        )

    def validate(self, input_data: Any) -> bool:
        health = self.health_check()
        return health.is_ready

    def _build_container_command(self) -> tuple[list[str], list[str]]:
        """Builds the container run command array and a safe redacted version for logging."""
        run_cmd = [self.container_engine, "run", "--rm", "-i"]
        safe_cmd = [self.container_engine, "run", "--rm", "-i"]

        if self.entrypoint:
            run_cmd.extend(["--entrypoint", self.entrypoint])
            safe_cmd.extend(["--entrypoint", self.entrypoint])

        if self.working_dir:
            run_cmd.extend(["-w", self.working_dir])
            safe_cmd.extend(["-w", self.working_dir])

        # Apply supported resource limits
        for key, flag in _SUPPORTED_RESOURCE_LIMITS.items():
            if key in self.resource_limits:
                val = str(self.resource_limits[key])
                run_cmd.extend([f"{flag}={val}"])
                safe_cmd.extend([f"{flag}={val}"])

        # Non-sensitive environment variables
        for k, v in self.environment_variables.items():
            run_cmd.extend(["-e", f"{k}={v}"])
            safe_cmd.extend(["-e", f"{k}={v}"])

        # Secret references resolved from host environment
        for container_var, host_env in self.secret_references.items():
            secret_val = os.environ.get(host_env, "")
            run_cmd.extend(["-e", f"{container_var}={secret_val}"])
            safe_cmd.extend(["-e", f"{container_var}=[REDACTED]"])

        run_cmd.append(self.image)
        safe_cmd.append(self.image)

        if self.command:
            run_cmd.extend(self.command)
            safe_cmd.extend(SecretRedactor.redact_command(self.command))

        return run_cmd, safe_cmd

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        actual_input_id = input_id
        if isinstance(inputs, CanonicalInput):
            actual_input_id = input_id or inputs.input_id
            raw_inputs = inputs.get_data()
        else:
            raw_inputs = dict(inputs)

        health = self.health_check()
        if not health.is_ready:
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs={"error": health.diagnostics},
                normalized_outputs={"error": health.diagnostics},
                execution_status="EXCEPTION",
                implementation_name=self.name,
                implementation_version=self.version,
                error_message=health.diagnostics,
                provenance={
                    "adapter_type": AdapterType.CONTAINER.value,
                    "role": str(self.role),
                    "health_status": health.status.value,
                },
            )

        # Container execution path
        import json
        import subprocess
        import time

        run_cmd, safe_cmd = self._build_container_command()
        logger.info(f"Executing container adapter '{self.name}' on input #{actual_input_id}: {' '.join(safe_cmd)}")

        start_time = time.perf_counter()
        try:
            stdin_data = json.dumps(raw_inputs)
            proc = subprocess.run(
                run_cmd,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

            out_text = proc.stdout.strip()
            try:
                raw_out = json.loads(out_text) if out_text else {}
            except Exception:
                raw_out = {"stdout": out_text}

            status = "SUCCESS" if proc.returncode == 0 else "EXCEPTION"
            err_msg = SecretRedactor.redact_string(proc.stderr.strip()) if proc.returncode != 0 else None

            safe_outputs = SecretRedactor.redact(raw_out)
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs=safe_outputs,
                normalized_outputs=self.normalize_output(safe_outputs),
                execution_status=status,
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=err_msg,
                provenance={
                    "adapter_type": AdapterType.CONTAINER.value,
                    "role": str(self.role),
                    "exit_code": proc.returncode,
                    "stdout": out_text,
                    "stderr": proc.stderr.strip() if proc.returncode != 0 else "",
                },
            )
        except subprocess.TimeoutExpired:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs={"error": f"Container execution timed out after {self.timeout_seconds} seconds"},
                normalized_outputs={"error": f"Container execution timed out after {self.timeout_seconds} seconds"},
                execution_status="TIMEOUT",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=f"Container execution timed out after {self.timeout_seconds} seconds",
                provenance={"adapter_type": AdapterType.CONTAINER.value, "role": str(self.role)},
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            safe_exc = SecretRedactor.redact_string(str(exc))
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs={"error": safe_exc},
                normalized_outputs={"error": safe_exc},
                execution_status="EXCEPTION",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=safe_exc,
                provenance={"adapter_type": AdapterType.CONTAINER.value, "role": str(self.role)},
            )
