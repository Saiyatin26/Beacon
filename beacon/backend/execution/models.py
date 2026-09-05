"""BEACON V2 — Application Execution Models, Sessions & Contracts.

Defines canonical data contracts for executing real reference/legacy and target/modern
applications across diverse runtimes (in-process functions, external processes, CLI,
HTTP/REST services, and containers) without domain coupling.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field

from common.contracts import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterRole,
    AdapterType,
    CanonicalInput,
    ExecutionStatus,
    Observation,
)


class ExecutionRequest(BaseModel):
    """Canonical request to execute an input against an implementation adapter."""
    execution_id: str = Field(
        default_factory=lambda: f"EXEC-{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:12]}"
    )
    application_id: str
    implementation_id: str
    role: Union[AdapterRole, str] = AdapterRole.TARGET
    input: Union[CanonicalInput, dict[str, Any]]
    timeout_seconds: float = 30.0
    environment_reference: Optional[str] = None
    trace_options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_canonical_input(self) -> CanonicalInput:
        if isinstance(self.input, CanonicalInput):
            return self.input
        return CanonicalInput(payload=self.input)


class ExecutionResult(BaseModel):
    """Structured execution outcome capturing process metrics, I/O, and observations."""
    execution_id: str
    session_id: Optional[str] = None
    application_id: str = ""
    implementation_id: str = ""
    role: Union[AdapterRole, str] = AdapterRole.TARGET
    status: ExecutionStatus = ExecutionStatus.CREATED
    observation: Optional[Observation] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: float = 0.0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    implementation_identity: dict[str, Any] = Field(default_factory=dict)
    runtime_identity: dict[str, Any] = Field(default_factory=dict)
    evidence_reference: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_observation(self, input_id: str = "") -> Observation:
        """Converts the execution result into a canonical Observation model."""
        if self.observation:
            return self.observation

        raw_out: dict[str, Any] = {}
        if self.stdout:
            try:
                raw_out = json.loads(self.stdout)
                if not isinstance(raw_out, dict):
                    raw_out = {"output": raw_out}
            except Exception:
                raw_out = {"stdout": self.stdout}
        elif self.error_message:
            raw_out = {"error": self.error_message}

        obs_status = "SUCCESS" if self.status == ExecutionStatus.SUCCEEDED else (
            "TIMEOUT" if self.status == ExecutionStatus.TIMEOUT else "EXCEPTION"
        )

        return Observation(
            input_id=input_id or self.execution_id,
            raw_inputs={},
            normalized_inputs={},
            raw_outputs=raw_out,
            normalized_outputs=raw_out,
            execution_status=obs_status,
            implementation_name=self.implementation_id or "unnamed_target",
            implementation_version=self.implementation_identity.get("version", "1.0.0"),
            execution_time_ms=self.duration_ms,
            error_message=self.error_message,
            provenance={
                "execution_id": self.execution_id,
                "role": str(self.role),
                "exit_code": self.exit_code,
                "status": self.status.value,
            },
        )


ExecutionRecord = ExecutionResult


class ExecutionSession(BaseModel):
    """Lifecycle tracking of an execution session (single run or batch certification sweep)."""
    session_id: str = Field(
        default_factory=lambda: f"SESS-{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:16]}"
    )
    application_id: str
    adapter_id: str
    role: Union[AdapterRole, str] = AdapterRole.TARGET
    start_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PREPARING
    records_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    timeout_count: int = 0
    implementation_identity: dict[str, Any] = Field(default_factory=dict)
    runtime_identity: dict[str, Any] = Field(default_factory=dict)
    evidence_hash: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def mark_completed(self, status: Optional[ExecutionStatus] = None) -> None:
        self.end_time = datetime.now(timezone.utc).isoformat()
        if status:
            self.status = status
        elif self.failed_count > 0 or self.timeout_count > 0:
            self.status = ExecutionStatus.FAILED
        else:
            self.status = ExecutionStatus.SUCCEEDED

    def compute_session_hash(self) -> str:
        """Computes deterministic hash across session metadata and execution metrics."""
        payload = {
            "session_id": self.session_id,
            "application_id": self.application_id,
            "adapter_id": self.adapter_id,
            "role": str(self.role),
            "start_time": self.start_time,
            "records_count": self.records_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "timeout_count": self.timeout_count,
            "implementation_identity": self.implementation_identity,
            "runtime_identity": self.runtime_identity,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
