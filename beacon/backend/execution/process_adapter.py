"""BEACON V2 — Safe External Process & CLI Implementation Adapter.

Executes external CLI binaries, scripts (Python, Java, Go, C#, Rust, Node, etc.),
and subprocesses with:
1. Untrusted argument array execution (shell=False).
2. Cross-platform process group creation and safe process tree termination on timeout.
3. Separate stdout/stderr stream capture with configurable byte limits and truncation markers.
4. Working directory sandboxing and explicit environment variable filtering.
5. Structured exit code and duration tracking.
"""

import concurrent.futures
from enum import Enum
import json
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


class ProcessExecutionMode(str, Enum):
    """Execution modality for ProcessAdapter."""
    ONE_SHOT = "one_shot"
    PERSISTENT = "persistent"


class ProcessLifecycleState(str, Enum):
    """Lifecycle state machine of a process instance."""
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    EXECUTING = "EXECUTING"
    EXITED = "EXITED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"



class ProcessAdapter(ImplementationAdapter):
    """Executes an external executable or script via subprocess with safety bounds."""

    def __init__(
        self,
        command: Union[str, list[str]],
        name: str = "external_process",
        version: str = "1.0.0",
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
        execution_mode: Union[ProcessExecutionMode, str] = ProcessExecutionMode.ONE_SHOT,
        working_directory: Optional[Union[str, Path]] = None,
        allowed_sandbox_root: Optional[Union[str, Path]] = None,
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
        if isinstance(execution_mode, str):
            try:
                self.execution_mode = ProcessExecutionMode(execution_mode.lower())
            except ValueError:
                self.execution_mode = ProcessExecutionMode.ONE_SHOT
        else:
            self.execution_mode = execution_mode
        self.command = [command] if isinstance(command, str) else list(command)
        self.working_directory = Path(working_directory).resolve() if working_directory else None
        self.allowed_sandbox_root = Path(allowed_sandbox_root).resolve() if allowed_sandbox_root else None
        self.allowed_env_vars = set(allowed_environment_variables or [
            "PATH", "SYSTEMROOT", "TEMP", "TMP", "HOMEPATH", "USERPROFILE", "LANG", "LC_ALL"
        ])
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.input_mapper = input_mapper or InputMapper()
        self.output_mapper = output_mapper or OutputMapper()
        self.metadata = metadata or {}
        self._process: Optional[subprocess.Popen] = None
        self._pid: Optional[int] = None
        self._thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self.lifecycle_state = ProcessLifecycleState.NOT_STARTED

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
            "execution_mode": self.execution_mode.value,
        }
        return hashlib.sha256(str(payload).encode()).hexdigest()


    def health_check(self) -> AdapterHealth:
        """Verifies executable existence and working directory validity against sandbox root."""
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

        if self.working_directory:
            try:
                allowed_roots = [self.allowed_sandbox_root] if self.allowed_sandbox_root else None
                SandboxedPathValidator.validate_working_directory(self.working_directory, allowed_roots=allowed_roots)
            except Exception as exc:
                return AdapterHealth(
                    adapter_id=f"{self.name}:{self.version}",
                    status=AdapterHealthStatus.MISCONFIGURED,
                    is_ready=False,
                    diagnostics=f"Working directory sandbox validation failed: {exc}",
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
        """Executes the process with inputs in either ONE_SHOT or PERSISTENT mode."""
        if self.execution_mode == ProcessExecutionMode.PERSISTENT:
            return self._execute_persistent(inputs, input_id=input_id)
        return self._execute_one_shot(inputs, input_id=input_id)

    def _execute_persistent(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        """Executes a single input against the persistent subprocess instance (PID X)."""
        actual_input_id = input_id
        if isinstance(inputs, CanonicalInput):
            actual_input_id = input_id or inputs.input_id
            raw_inputs = inputs.get_data()
        else:
            raw_inputs = dict(inputs)

        safe_inputs = SecretRedactor.redact(raw_inputs)

        # 1. State Validation: Process must have been started
        if self.lifecycle_state == ProcessLifecycleState.NOT_STARTED or self._process is None:
            err_msg = (
                f"ProcessAdapter '{self.name}' is configured in PERSISTENT mode but has not been started. "
                f"start() must be invoked before execute()."
            )
            logger.error(f"[PERSISTENT] {err_msg}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs={"error": err_msg},
                normalized_outputs={"error": err_msg},
                execution_status="PROCESS_NOT_RUNNING",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=0.0,
                error_message=err_msg,
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "execution_mode": ProcessExecutionMode.PERSISTENT.value,
                    "role": str(self.role),
                    "error_type": "ProcessNotRunningError",
                    "lifecycle_state": self.lifecycle_state.value,
                },
            )

        # 2. State Validation: Process must still be alive
        poll_code = self._process.poll()
        if poll_code is not None:
            self.lifecycle_state = ProcessLifecycleState.EXITED
            err_msg = (
                f"Persistent process '{self.name}' (PID {self._pid}) has exited unexpectedly "
                f"with returncode {poll_code} before input execution."
            )
            logger.error(f"[PERSISTENT] {err_msg}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs={"error": err_msg},
                normalized_outputs={"error": err_msg},
                execution_status="PROCESS_NOT_RUNNING",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=0.0,
                error_message=err_msg,
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "execution_mode": ProcessExecutionMode.PERSISTENT.value,
                    "role": str(self.role),
                    "error_type": "ProcessNotRunningError",
                    "exit_code": poll_code,
                    "pid": self._pid,
                    "process_id": self._pid,
                    "lifecycle_state": self.lifecycle_state.value,
                },
            )

        # 3. Mark EXECUTING
        self.lifecycle_state = ProcessLifecycleState.EXECUTING
        start_time = time.perf_counter()
        logger.info(f"[PERSISTENT] Executing input #{actual_input_id} on persistent PID {self._pid}")

        # 4. Write line-delimited JSON payload to stdin
        payload_str = json.dumps(raw_inputs) + "\n"
        try:
            if self._process.stdin is None or self._process.stdin.closed:
                raise BrokenPipeError("stdin stream is closed")
            self._process.stdin.write(payload_str)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as write_err:
            self.lifecycle_state = ProcessLifecycleState.EXITED
            poll_code = self._process.poll()
            err_msg = f"Failed to dispatch input to persistent process PID {self._pid} (Broken Pipe): {write_err}"
            logger.error(f"[PERSISTENT] {err_msg}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs={"error": err_msg},
                normalized_outputs={"error": err_msg},
                execution_status="PROCESS_NOT_RUNNING",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 3),
                error_message=err_msg,
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "execution_mode": ProcessExecutionMode.PERSISTENT.value,
                    "role": str(self.role),
                    "error_type": "ProcessNotRunningError",
                    "exit_code": poll_code,
                    "pid": self._pid,
                    "process_id": self._pid,
                },
            )

        # 5. Read response line with timeout
        if self._thread_pool is None:
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        try:
            future = self._thread_pool.submit(self._process.stdout.readline)
            resp_line = future.result(timeout=self.timeout_seconds)
        except concurrent.futures.TimeoutError:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            logger.warning(f"[PERSISTENT] Process '{self.name}' (PID {self._pid}) timed out after {self.timeout_seconds}s.")
            self.lifecycle_state = ProcessLifecycleState.FAILED
            self._terminate_process_tree(self._process)
            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs={"error": f"Execution timed out after {self.timeout_seconds}s"},
                normalized_outputs={"error": f"Execution timed out after {self.timeout_seconds}s"},
                execution_status="TIMEOUT",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=f"Execution timed out after {self.timeout_seconds} seconds",
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "execution_mode": ProcessExecutionMode.PERSISTENT.value,
                    "role": str(self.role),
                    "error_type": "TimeoutError",
                    "pid": self._pid,
                    "process_id": self._pid,
                    "lifecycle_state": self.lifecycle_state.value,
                },
            )

        latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

        # 6. Check for EOF
        if not resp_line:
            self.lifecycle_state = ProcessLifecycleState.EXITED
            poll_code = self._process.poll()
            err_msg = f"Persistent process (PID {self._pid}) closed stdout stream unexpectedly."
            logger.error(f"[PERSISTENT] {err_msg}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=safe_inputs,
                normalized_inputs=safe_inputs,
                raw_outputs={"error": err_msg},
                normalized_outputs={"error": err_msg},
                execution_status="PROCESS_NOT_RUNNING",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=err_msg,
                provenance={
                    "adapter_type": AdapterType.PROCESS.value,
                    "execution_mode": ProcessExecutionMode.PERSISTENT.value,
                    "role": str(self.role),
                    "error_type": "ProcessNotRunningError",
                    "exit_code": poll_code,
                    "pid": self._pid,
                    "process_id": self._pid,
                    "lifecycle_state": self.lifecycle_state.value,
                },
            )

        # 7. Transition back to RUNNING and parse response
        self.lifecycle_state = ProcessLifecycleState.RUNNING
        resp_text = resp_line.strip()
        stdout_truncated = False

        if len(resp_text.encode("utf-8")) > self.max_output_bytes:
            resp_text = resp_text[:self.max_output_bytes] + "\n[TRUNCATED: Output exceeded size limit]"
            stdout_truncated = True

        safe_stdout = SecretRedactor.redact_string(resp_text)

        try:
            parsed_json = json.loads(resp_text)
            raw_out = parsed_json if isinstance(parsed_json, dict) else {"output": parsed_json}
        except Exception:
            raw_out = {"stdout": safe_stdout}

        mapped_outputs = self.output_mapper.map_output(
            raw_output=raw_out,
            stdout=safe_stdout,
            exit_code=0,
        )
        safe_outputs = SecretRedactor.redact(mapped_outputs)
        norm_outputs = self.normalize_output(safe_outputs)

        return Observation(
            input_id=actual_input_id,
            raw_inputs=safe_inputs,
            normalized_inputs=safe_inputs,
            raw_outputs=safe_outputs,
            normalized_outputs=norm_outputs,
            execution_status="SUCCESS",
            implementation_name=self.name,
            implementation_version=self.version,
            execution_time_ms=latency_ms,
            provenance={
                "adapter_type": AdapterType.PROCESS.value,
                "execution_mode": ProcessExecutionMode.PERSISTENT.value,
                "role": str(self.role),
                "pid": self._pid,
                "process_id": self._pid,
                "exit_code": 0,
                "stdout": safe_stdout,
                "stdout_truncated": stdout_truncated,
                "lifecycle_state": self.lifecycle_state.value,
            },
        )

    def _execute_one_shot(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        """Executes a single input by launching a dedicated one-shot subprocess."""
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
        logger.info(f"Executing one-shot process adapter '{self.name}' on input #{actual_input_id}: {safe_log_cmd}")

        start_time = time.perf_counter()
        process = None
        stdout_text = ""
        stderr_text = ""
        exit_code = None
        execution_status = "SUCCESS"
        error_msg: Optional[str] = None
        proc_pid = None

        try:
            # Validate working directory containment before spawning subprocess
            if self.working_directory:
                allowed_roots = [self.allowed_sandbox_root] if self.allowed_sandbox_root else None
                SandboxedPathValidator.validate_working_directory(self.working_directory, allowed_roots=allowed_roots)

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
            proc_pid = process.pid

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
                    "execution_mode": ProcessExecutionMode.ONE_SHOT.value,
                    "role": str(self.role),
                    "pid": proc_pid,
                    "process_id": proc_pid,
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
                    "execution_mode": ProcessExecutionMode.ONE_SHOT.value,
                    "role": str(self.role),
                    "pid": proc_pid,
                    "process_id": proc_pid,
                    "error_type": type(exc).__name__,
                },
            )

    def _terminate_process_tree(self, process: subprocess.Popen, timeout_seconds: float = 3.0) -> None:
        """Safely terminates a subprocess and its child processes cross-platform."""
        if process.poll() is not None:
            return

        pid = process.pid
        try:
            if sys.platform == "win32":
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=timeout_seconds)
                except Exception:
                    process.kill()
            else:
                try:
                    os.killpg(os.getpgid(pid), 15)  # SIGTERM
                    try:
                        process.wait(timeout=timeout_seconds)
                    except subprocess.TimeoutExpired:
                        os.killpg(os.getpgid(pid), 9)  # SIGKILL
                except Exception:
                    process.kill()
        except Exception as exc:
            logger.debug(f"Process termination notice for PID {pid}: {exc}")
        finally:
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass

    def start(self, context: Optional[dict[str, Any]] = None) -> Any:
        """Lifecycle hook: Starts the process as a persistent service if in PERSISTENT mode."""
        if self.execution_mode == ProcessExecutionMode.ONE_SHOT:
            # Section 10: In ONE_SHOT mode, start() must not accidentally create an unnecessary persistent process.
            logger.info(f"ProcessAdapter '{self.name}' start() called in ONE_SHOT mode (no persistent process spawned).")
            self.lifecycle_state = ProcessLifecycleState.RUNNING
            return None

        # Persistent Mode
        if self._process is not None and self._process.poll() is None:
            logger.info(f"Persistent process '{self.name}' is already running (PID: {self._pid})")
            return self._process

        effective_cmd = list(self.command)
        filtered_env = self._build_env()
        cwd = str(self.working_directory) if self.working_directory else None

        if self.working_directory:
            allowed_roots = [self.allowed_sandbox_root] if self.allowed_sandbox_root else None
            SandboxedPathValidator.validate_working_directory(self.working_directory, allowed_roots=allowed_roots)

        creationflags = 0
        preexec_fn = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            preexec_fn = getattr(os, "setsid", None)

        try:
            self._process = subprocess.Popen(
                effective_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line-buffered text
                cwd=cwd,
                env=filtered_env,
                shell=False,
                creationflags=creationflags,
                preexec_fn=preexec_fn,
            )
            self._pid = self._process.pid
            self.lifecycle_state = ProcessLifecycleState.RUNNING
            if self._thread_pool is None:
                self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            logger.info(f"Started persistent process '{self.name}' (PID: {self._pid})")
            return self._process
        except Exception as exc:
            self.lifecycle_state = ProcessLifecycleState.FAILED
            logger.error(f"Failed to start persistent process for '{self.name}': {exc}")
            raise

    def stop(self, context: Optional[dict[str, Any]] = None) -> None:
        """Lifecycle hook: Gracefully terminates the running process."""
        if self._process is not None:
            pid = self._pid
            logger.info(f"Stopping process adapter '{self.name}' (PID: {pid})")
            try:
                if self._process.poll() is None:
                    try:
                        if self._process.stdin and not self._process.stdin.closed:
                            self._process.stdin.write(json.dumps({"command": "exit"}) + "\n")
                            self._process.stdin.flush()
                            self._process.wait(timeout=1.0)
                    except Exception:
                        pass
                if self._process.poll() is None:
                    self._terminate_process_tree(self._process)
            finally:
                self._process = None
                self._pid = None
                self.lifecycle_state = ProcessLifecycleState.STOPPED

        if self._thread_pool is not None:
            self._thread_pool.shutdown(wait=False)
            self._thread_pool = None

    def get_process(self) -> Optional[Any]:
        """Returns the active subprocess.Popen handle."""
        return self._process

    def cleanup(self) -> None:
        """Lifecycle hook: Ensures process termination and resource cleanup."""
        self.stop()



class CliAdapter(ProcessAdapter):

    """Convenience alias and specialization for CLI tools and scripts."""

    def __init__(self, command: Union[str, list[str]], name: str = "cli_adapter", **kwargs):
        super().__init__(command=command, name=name, **kwargs)
        self.adapter_type = AdapterType.CLI
