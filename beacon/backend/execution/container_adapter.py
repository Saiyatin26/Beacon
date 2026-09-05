"""BEACON V2 — Container Implementation Adapter.

Executes applications inside isolated container runtimes (Docker, Podman, OCI).
Features capability-based detection: if Docker is absent from the host system,
reports structured UNAVAILABLE health diagnostics without failing BEACON startup.
"""

import logging
import shutil
from typing import Any, Optional, Union

from certification.adapters import AdapterRole, ImplementationAdapter
from certification.models import CanonicalInput, Observation
from .models import AdapterCapabilities, AdapterHealth, AdapterHealthStatus, AdapterType

logger = logging.getLogger("beacon.execution.container")


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
        self.resource_limits = dict(resource_limits or {})
        self.timeout_seconds = timeout_seconds
        self.name = name
        self.version = version
        self.role = role
        self.adapter_type = AdapterType.CONTAINER
        self.metadata = metadata or {}

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
                details={"image": self.image, "engine": self.container_engine},
            )

        return AdapterHealth(
            adapter_id=f"{self.name}:{self.version}",
            status=AdapterHealthStatus.AVAILABLE,
            is_ready=True,
            diagnostics=f"Container engine '{self.container_engine}' is present at '{engine_path}'.",
            capabilities=self.capabilities,
            details={"image": self.image, "engine_path": engine_path},
        )

    def validate(self, input_data: Any) -> bool:
        health = self.health_check()
        return health.is_ready

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

        # Container execution path: delegate via subprocess with container run command
        import json
        import subprocess
        import time

        run_cmd = [self.container_engine, "run", "--rm", "-i"]
        if self.working_dir:
            run_cmd.extend(["-w", self.working_dir])
        for k, v in self.environment_variables.items():
            run_cmd.extend(["-e", f"{k}={v}"])
        run_cmd.append(self.image)
        if self.command:
            run_cmd.extend(self.command)

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
            err_msg = proc.stderr.strip() if proc.returncode != 0 else None

            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=raw_inputs,
                raw_outputs=raw_out,
                normalized_outputs=self.normalize_output(raw_out),
                execution_status=status,
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=err_msg,
                provenance={
                    "adapter_type": AdapterType.CONTAINER.value,
                    "role": str(self.role),
                    "exit_code": proc.returncode,
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
                provenance={"adapter_type": AdapterType.CONTAINER.value, "role": str(self.role)},
            )
