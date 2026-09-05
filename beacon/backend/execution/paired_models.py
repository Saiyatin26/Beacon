"""BEACON V2 — Phase 3 Paired Execution Models & Session Abstractions.

Defines data contracts for coordinated paired execution of Reference and Target
applications, tracking per-input correlations, multi-stage lifecycles, and reproducibility.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


from common.contracts import AdapterRole
from .evidence_models import EvidenceConfiguration
from .readiness import ReadinessConfig


class PairedExecutionStatus(str, Enum):
    """Lifecycle states of a paired execution session."""
    NOT_STARTED = "NOT_STARTED"
    PREPARING = "PREPARING"
    REFERENCE_STARTING = "REFERENCE_STARTING"
    REFERENCE_READY = "REFERENCE_READY"
    REFERENCE_RUNNING = "REFERENCE_RUNNING"
    REFERENCE_CLEANUP = "REFERENCE_CLEANUP"
    TARGET_STARTING = "TARGET_STARTING"
    TARGET_READY = "TARGET_READY"
    TARGET_RUNNING = "TARGET_RUNNING"
    TARGET_CLEANUP = "TARGET_CLEANUP"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class PairedExecutionItemResult(BaseModel):
    """Correlated execution outcome for a single input executed on both Reference and Target."""
    input_id: str
    correlation_id: str
    reference_execution_id: Optional[str] = None
    target_execution_id: Optional[str] = None
    reference_status: Optional[str] = None
    target_status: Optional[str] = None
    reference_duration_ms: float = 0.0
    target_duration_ms: float = 0.0
    reference_exit_code: Optional[int] = None
    target_exit_code: Optional[int] = None
    evidence_ids: list[str] = Field(default_factory=list)


class PairedExecutionRequest(BaseModel):
    """High-level request representing an end-to-end paired execution run."""
    application_id: str
    reference_adapter_id: Optional[str] = None
    target_adapter_id: Optional[str] = None
    reference_adapter: Optional[Any] = None
    target_adapter: Optional[Any] = None
    input_set_id: Optional[str] = None
    custom_inputs: Optional[list[dict[str, Any]]] = None
    allow_synthetic_inputs: Optional[bool] = None
    evidence_config: Optional[EvidenceConfiguration] = None
    readiness_config_ref: Optional[ReadinessConfig] = None
    readiness_config_target: Optional[ReadinessConfig] = None
    timeout_seconds: float = 30.0
    correlation_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(arbitrary_types_allowed=True)


class PairedExecutionSession(BaseModel):

    """Comprehensive tracking of a paired reference-target execution session."""
    session_id: str = Field(
        default_factory=lambda: f"PAIRED-SESS-{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:12]}"
    )
    correlation_id: str = Field(
        default_factory=lambda: f"CORR-{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:12]}"
    )
    application_id: str
    reference_adapter_name: str
    target_adapter_name: str
    input_set_id: str
    input_set_hash: str
    status: PairedExecutionStatus = PairedExecutionStatus.NOT_STARTED
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_inputs: int = 0
    executed_inputs: int = 0
    paired_results: list[PairedExecutionItemResult] = Field(default_factory=list)
    bundle_id: Optional[str] = None
    bundle_hash: Optional[str] = None
    error_summary: Optional[str] = None
    reproducibility_metadata: dict[str, Any] = Field(default_factory=dict)

    def mark_completed(self, status: Optional[PairedExecutionStatus] = None) -> None:
        """Transitions session to a terminal status and records completion timestamp."""
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if status:
            self.status = status
        elif self.error_summary:
            self.status = PairedExecutionStatus.PARTIAL
        else:
            self.status = PairedExecutionStatus.COMPLETED

    def compute_session_hash(self) -> str:
        """Computes a deterministic digest of the session's core execution attributes."""
        payload = {
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "application_id": self.application_id,
            "reference_adapter": self.reference_adapter_name,
            "target_adapter": self.target_adapter_name,
            "input_set_id": self.input_set_id,
            "input_set_hash": self.input_set_hash,
            "total_inputs": self.total_inputs,
            "executed_inputs": self.executed_inputs,
            "bundle_hash": self.bundle_hash,
            "status": self.status.value,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
