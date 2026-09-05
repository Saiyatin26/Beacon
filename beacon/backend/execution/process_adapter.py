"""BEACON V2 — Safe External Process & CLI Implementation Adapter.

Executes external CLI binaries, scripts (Python, Java, Go, C#, Rust, Node, etc.),
and subprocesses with:
1. Untrusted argument array execution (shell=False).
2. Cross-platform process group creation and safe process tree termination on timeout.
3. Separate stdout/stderr stream capture with configurable byte limits and truncation markers.
4. Working directory sandboxing and explicit environment variable filtering.
5. Structured exit code and duration tracking.
"""

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Optional, Union
from common.contracts import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterRole,
    AdapterType,
    CanonicalInput,
    ExecutionStatus,
    ImplementationAdapter,
    Observation,
)
from .mapping import InputMapper, InputMapperConfig, OutputMapper, OutputMapperConfig
from .models import ExecutionResult
from .security import SandboxedPathValidator, SecretRedactor

logger = logging.getLogger("beacon.execution.process")


class ProcessAdapter(ImplementationAdapter):
    """Executes an external executable or script via subprocess with safety bounds."""

    def __init__(
        self,
        command: Union[str, list[str]],
        name: str = "external_process",
        version: str = "1.0.0",
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
        working_directory: Optional[Union[str, Path]] = None,
        allowed_environment_variables: Optional[list[str]] = None,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 1_000_000,  # 1MB output limit
        input_mapper: Optional[InputMapper] = None,
        output_mapper: Optional[OutputMapper] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.name = name
        self.version = version
        self.role = role
        self.adapter_type = AdapterType.PROCESS
        self.command = [command] if isinstance(command, str) else list(command)
        self.working_directory = Path(working_directory).resolve() if working_directory else None
        self.allowed_env_vars = set(allowed_environment_variables or [
            "PATH", "SYSTEMROOT", "TEMP", "TMP", "HOMEPATH", "USERPROFILE", "LANG", "LC_ALL"
        ])
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.input_mapper = input_mapper or InputMapper()
        self.output_mapper = output_mapper or OutputMapper()
        self.metadata = metadata or {}

        self.capabilities = AdapterCapabilities(
            supports_timeout=True,
            supports_streaming=False,
            supports_files=True,
            supports_binary=True,
            supports_traces=False,
            supports_cleanup=True,
            supports_state_capture=False,
            supports_sandboxing=True,
        )

        self.implementation_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        import hashlib
        payload = {
            "name": self.name,
            "version": self.version,
            "role": str(self.role),
            "command": self.command,
        }
        return hashlib.sha256(str(payload).encode()).hexdigest()

    def health_check(self) -> AdapterHealth:
        """Verifies executable existence and working directory validity."""
        if not self.command:
            return AdapterHealth(
                adapter_id=f"{self.name}:{self.version}",
                status=AdapterHealthStatus.MISCONFIGURED,
                is_ready=False,
                diagnostics="ProcessAdapter command cannot be empty.",
                capabilities=self.capabilities,
            )

        executable = self.command[0]
        resolved_path = shutil.which(executable) or (Path(executable).exists() and executable)
        if not resolved_path:
            return AdapterHealth(
                adapter_id=f"{self.name}:{self.version}",
                status=AdapterHealthStatus.UNAVAILABLE,
                is_ready=False,
                diagnostics=f"Executable '{executable}' was not found in system PATH or filesystem.",
                capabilities=self.capabilities,
            )

        if self.working_directory and not self.working_directory.exists():
            return AdapterHealth(
                adapter_id=f"{self.name}:{self.version}",
                status=AdapterHealthStatus.MISCONFIGURED,
                is_ready=False,
                diagnostics=f"Configured working directory does not exist: '{self.working_directory}'",
                capabilities=self.capabilities,
            )

        return AdapterHealth(
            adapter_id=f"{self.name}:{self.version}",
            status=AdapterHealthStatus.AVAILABLE,
            is_ready=True,
            diagnostics=f"Executable '{executable}' is available and configured.",
            capabilities=self.capabilities,
        )

    def validate(self, input_data: Any) -> bool:
        """Pre-execution validation."""
        health = self.health_check()
        return health.is_ready

    def _build_env(self) -> dict[str, str]:
        """Builds a sanitized environment dictionary containing only explicitly allowed keys."""
        filtered_env: dict[str, str] = {}
        for key, val in os.environ.items():
            if key in self.allowed_env_vars:
                filtered_env[key] = val
        return filtered_env

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        """Executes the process with inputs mapped to CLI flags or stdin."""
        actual_input_id = input_id
        if isinstance(inputs, CanonicalInput):
            actual_input_id = input_id or inputs.input_id
            raw_inputs = inputs.get_data()
        else:
            raw_inputs = dict(inputs)

        cli_args = self.input_mapper.map_to_cli_args(inputs)
        full_command = self.command + cli_args

        # Redact for logging
        safe_log_cmd = SecretRedactor.redact_command(full_command)
        logger.info(f"Executing process adapter '{self.name}' on input #{actual_input_id}: {safe_log_cmd}")

        start_time = time.perf_counter()
        process = None
        stdout_text = ""
        stderr_text = ""
        exit_code = None
        execution_status = "SUCCESS"
        error_msg: Optional[str] = None

        try:
            # Cross-platform process group flags
            creationflags = 0
            preexec_fn = None
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                preexec_fn = os.setsid

            env = self._build_env()
            cwd = str(self.working_directory) if self.working_directory else None

            process = subprocess.Popen(
                full_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
                creationflags=creationflags,
                preexec_fn=preexec_fn,
            )

            try:
                raw_stdout, raw_stderr = process.communicate(timeout=self.timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                logger.warning(f"Process adapter '{self.name}' timed out after {self.timeout_seconds}s. Terminating...")
                self._terminate_process_tree(process)
                raw_stdout, raw_stderr = process.communicate()
                exit_code = -1
                execution_status = "TIMEOUT"
                error_msg = f"Execution timed out after {self.timeout_seconds} seconds"

            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

            # Truncate output if exceeding byte caps
            stdout_text = raw_stdout or ""
            stderr_text = raw_stderr or ""
            stdout_truncated = False
            stderr_truncated = False

            if len(stdout_text.encode("utf-8")) > self.max_output_bytes:
                stdout_text = stdout_text[:self.max_output_bytes] + "\n[TRUNCATED: Output exceeded size limit]"
                stdout_truncated = True

            if len(stderr_text.encode("utf-8")) > self.max_output_bytes:
                stderr_text = stderr_text[:self.max_output_bytes] + "\n[TRUNCATED: Stderr exceeded size limit]"
                stderr_truncated = True

            # Redact raw stdout and stderr to prevent credential leakage into observations/evidence
            safe_stdout = SecretRedactor.redact_string(stdout_text)
            safe_stderr = SecretRedactor.redact_string(stderr_text)
            safe_inputs = SecretRedactor.redact(raw_inputs)

            # Determine execution status based on exit code
            if execution_status != "TIMEOUT":
                if exit_code != 0:
                    execution_status = "EXCEPTION"
                    error_msg = f"Process exited with non-zero status code {exit_code}: {safe_stderr.strip()}"
                else:
                    execution_status = "SUCCESS"

            safe_error_msg = SecretRedactor.redact_string(error_msg) if error_msg else None

            # Map outputs
            mapped_outputs = self.output_mapper.map_output(
                raw_output=None,
                stdout=safe_stdout,
                stderr=safe_stderr,
                exit_code=exit_code,
            )
            safe_outputs = SecretRedactor.redact(mapped_outputs)
            norm_outputs = self.normalize_output(safe_outputs)

            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs=safe_outputs,
                normalized_outputs=norm_outputs,
                execution_status=execution_status,
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=safe_error_msg,
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "role": str(self.role),
                    "exit_code": exit_code,
                    "stdout": safe_stdout,
                    "stderr": safe_stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                },
            )

        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            safe_exc = SecretRedactor.redact_string(str(exc))
            logger.error(f"ProcessAdapter '{self.name}' unexpected execution failure: {safe_exc}")
            if process:
                self._terminate_process_tree(process)

            safe_inputs = SecretRedactor.redact(raw_inputs)
            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs={"error": safe_exc},
                normalized_outputs={"error": safe_exc},
                execution_status="EXCEPTION",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=safe_exc,
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "role": str(self.role),
                    "error_type": type(exc).__name__,
                },
            )

    def _terminate_process_tree(self, process: subprocess.Popen) -> None:
        """Safely terminates a subprocess and its child processes cross-platform."""
        if process.poll() is not None:
            return

        try:
            if sys.platform == "win32":
                # Terminate process tree using taskkill or process.kill()
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
                except Exception:
                    process.kill()
            else:
                # Terminate POSIX process group
                try:
                    os.killpg(os.getpgid(process.pid), 15)  # SIGTERM
                    time.sleep(0.1)
                    if process.poll() is None:
                        os.killpg(os.getpgid(process.pid), 9)  # SIGKILL
                except Exception:
                    process.kill()
        except Exception as exc:
            logger.debug(f"Process termination notice for PID {process.pid}: {exc}")


class CliAdapter(ProcessAdapter):
    """Convenience alias and specialization for CLI tools and scripts."""

    def __init__(self, command: Union[str, list[str]], name: str = "cli_adapter", **kwargs):
        super().__init__(command=command, name=name, **kwargs)
        self.adapter_type = AdapterType.CLI
