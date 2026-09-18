"""BEACON V2 — Phase 11 Canonical Workflow Domain Models.

Defines the core data contracts for production workflow orchestration, run tracking,
machine-readable error taxonomies, and end-to-end certification results.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class WorkflowState(str, Enum):
    """Execution state machine for the canonical V2 certification workflow."""
    INITIALIZED = "INITIALIZED"
    VALIDATING = "VALIDATING"
    CAPTURING_EVIDENCE = "CAPTURING_EVIDENCE"
    EVALUATING = "EVALUATING"
    RESOLVING_ORACLES = "RESOLVING_ORACLES"
    RESOLVING_THRESHOLDS = "RESOLVING_THRESHOLDS"
    CERTIFYING = "CERTIFYING"
    EXPLAINING = "EXPLAINING"
    PERSISTING = "PERSISTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class FinalizationState(str, Enum):
    """Durable state progression during workflow persistence and finalization."""
    NOT_STARTED = "NOT_STARTED"
    PERSISTING = "PERSISTING"
    CERTIFICATION_VERIFIED = "CERTIFICATION_VERIFIED"
    AUDIT_VERIFIED = "AUDIT_VERIFIED"
    FINALIZATION_PENDING = "FINALIZATION_PENDING"
    IDEMPOTENCY_FINALIZED = "IDEMPOTENCY_FINALIZED"
    COMPLETED = "COMPLETED"


class WorkflowStateTransitionError(RuntimeError):
    """Raised when an illegal or invariant-violating workflow state transition is attempted."""
    pass


VALID_WORKFLOW_STATE_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.INITIALIZED: {WorkflowState.VALIDATING, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.VALIDATING: {WorkflowState.CAPTURING_EVIDENCE, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.CAPTURING_EVIDENCE: {WorkflowState.EVALUATING, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.EVALUATING: {WorkflowState.RESOLVING_ORACLES, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.RESOLVING_ORACLES: {WorkflowState.RESOLVING_THRESHOLDS, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.RESOLVING_THRESHOLDS: {WorkflowState.CERTIFYING, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.CERTIFYING: {WorkflowState.EXPLAINING, WorkflowState.PERSISTING, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.EXPLAINING: {WorkflowState.PERSISTING, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.PERSISTING: {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.COMPLETED: set(),
    WorkflowState.FAILED: {WorkflowState.FAILED, WorkflowState.INCONCLUSIVE},
    WorkflowState.INCONCLUSIVE: {WorkflowState.INCONCLUSIVE, WorkflowState.FAILED},
}


def is_valid_state_transition(current: WorkflowState, target: WorkflowState, is_recovery: bool = False) -> bool:
    """Validates whether a workflow state transition is permissible."""
    if current == target:
        return True
    if is_recovery:
        # In recovery, an uncompleted in-flight run may transition strictly to COMPLETED, FAILED, or INCONCLUSIVE.
        # However, COMPLETED is strictly forbidden from early uncertified stages (must have reached CERTIFYING, EXPLAINING, or PERSISTING).
        if target == WorkflowState.COMPLETED:
            return current in (WorkflowState.CERTIFYING, WorkflowState.EXPLAINING, WorkflowState.PERSISTING)
        return target in (WorkflowState.FAILED, WorkflowState.INCONCLUSIVE)
    allowed = VALID_WORKFLOW_STATE_TRANSITIONS.get(current, set())
    return target in allowed


def transition_workflow_state(
    run: "WorkflowRun",
    target_state: WorkflowState,
    reason: str = "",
    metadata: Optional[dict[str, Any]] = None,
    is_recovery: bool = False,
) -> "WorkflowRun":
    """Central authoritative state transition function. Validates transitions and enforces state invariants."""
    current_state = run.state
    if not is_valid_state_transition(current_state, target_state, is_recovery=is_recovery):
        raise WorkflowStateTransitionError(
            f"Illegal workflow state transition from '{current_state.value}' to '{target_state.value}' "
            f"(reason: {reason}, is_recovery={is_recovery})"
        )

    if metadata:
        run.metadata.update(metadata)

    # State Invariant Enforcements
    if target_state == WorkflowState.COMPLETED:
        if not run.certification_id:
            raise WorkflowStateTransitionError("Cannot transition to COMPLETED without valid certification_id.")
        if not run.threshold_resolution_id:
            raise WorkflowStateTransitionError("Cannot transition to COMPLETED without threshold_resolution_id.")
        if not run.execution_fingerprint:
            raise WorkflowStateTransitionError("Cannot transition to COMPLETED without Stage-B execution_fingerprint.")
        if not is_recovery and current_state != WorkflowState.PERSISTING:
            raise WorkflowStateTransitionError(f"Cannot transition to COMPLETED directly from '{current_state.value}'.")
        if not run.metadata.get("audit_persisted") and not is_recovery:
            raise WorkflowStateTransitionError("Cannot transition to COMPLETED without verified audit persistence.")

    now_iso = datetime.now(timezone.utc).isoformat()
    run.state = target_state
    run.updated_at = now_iso
    if target_state in (WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.INCONCLUSIVE):
        run.completed_at = now_iso

    if metadata:
        run.metadata.update(metadata)
    if reason:
        transition_history = run.metadata.setdefault("state_transitions", [])
        transition_history.append({
            "from_state": current_state.value,
            "to_state": target_state.value,
            "reason": reason,
            "timestamp": now_iso,
            "is_recovery": is_recovery,
        })

    return run


def compute_execution_fingerprint(
    application_id: str,
    ref_target_id: str,
    ref_version: str,
    ref_source_hash: str,
    target_id: str,
    target_version: str,
    target_source_hash: str,
    input_set_hash: str,
    input_count: int,
    policy_id: Optional[str] = None,
    rule_config_mode: Optional[str] = None,
) -> str:
    """Computes deterministic Stage B execution identity over resolved material inputs."""
    payload = {
        "application_id": application_id,
        "ref_target_id": ref_target_id,
        "ref_version": ref_version,
        "ref_source_hash": ref_source_hash,
        "target_id": target_id,
        "target_version": target_version,
        "target_source_hash": target_source_hash,
        "input_set_hash": input_set_hash,
        "input_count": input_count,
        "policy_id": policy_id or "",
        "rule_config_mode": rule_config_mode or "",
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class WorkflowErrorCode(str, Enum):
    """Machine-readable, unambiguous error taxonomy for V2 workflow failures."""
    INVALID_INPUT = "INVALID_INPUT"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    APPLICATION_NOT_FOUND = "APPLICATION_NOT_FOUND"
    ADAPTER_RESOLUTION_FAILED = "ADAPTER_RESOLUTION_FAILED"
    EVIDENCE_CAPTURE_FAILED = "EVIDENCE_CAPTURE_FAILED"
    EVALUATION_FAILED = "EVALUATION_FAILED"
    ORACLE_AUTHORITY_MISSING = "ORACLE_AUTHORITY_MISSING"
    THRESHOLD_AUTHORITY_MISSING = "THRESHOLD_AUTHORITY_MISSING"
    THRESHOLD_FINGERPRINT_MISMATCH = "THRESHOLD_FINGERPRINT_MISMATCH"
    CERTIFICATION_FAILED = "CERTIFICATION_FAILED"
    CERTIFICATION_INCONCLUSIVE = "CERTIFICATION_INCONCLUSIVE"
    EXPLANATION_GROUNDING_FAILED = "EXPLANATION_GROUNDING_FAILED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    CONCURRENCY_CONFLICT = "CONCURRENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class WorkflowRunRequest(BaseModel):
    """Structured request payload to execute canonical V2 certification."""
    model_config = ConfigDict(extra="ignore")

    application_id: str
    target_index: int = 0
    custom_inputs: Optional[list[dict[str, Any]]] = None
    sample_count: Optional[int] = None
    policy_min_equivalence_score: float = 0.999
    policy_min_oracle_coverage: float = 0.0
    allow_warnings: bool = False
    explain: bool = True
    explanation_mode: Literal["deterministic", "llm", "auto"] = "deterministic"
    use_company_knowledge: bool = False
    enable_discovery: bool = False
    evaluation_mode: Optional[str] = "CONTROLLED"
    force_recompute: bool = False
    idempotency_key: Optional[str] = None
    user_id: str = "system"

    def compute_request_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over all material request fields."""
        payload = {
            "application_id": self.application_id,
            "target_index": self.target_index,
            "custom_inputs": self.custom_inputs or [],
            "sample_count": self.sample_count,
            "policy_min_equivalence_score": round(self.policy_min_equivalence_score, 6),
            "policy_min_oracle_coverage": round(self.policy_min_oracle_coverage, 6),
            "allow_warnings": self.allow_warnings,
            "explain": self.explain,
            "explanation_mode": self.explanation_mode,
            "use_company_knowledge": self.use_company_knowledge,
        }
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class WorkflowRun(BaseModel):
    """Authoritative lifecycle record of a specific V2 certification execution."""
    model_config = ConfigDict(extra="ignore")

    workflow_run_id: str
    application_id: str
    request_fingerprint: str
    execution_fingerprint: Optional[str] = None
    input_set_id: Optional[str] = None
    input_set_hash: Optional[str] = None
    state: WorkflowState = WorkflowState.INITIALIZED
    finalization_state: Optional[FinalizationState] = FinalizationState.NOT_STARTED
    error_code: Optional[WorkflowErrorCode] = None
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

    # Linked Stage Authoritative Identifiers
    evidence_session_id: Optional[str] = None
    evidence_bundle_id: Optional[str] = None
    evaluation_id: Optional[str] = None
    oracle_set_id: Optional[str] = None
    oracle_set_hash: Optional[str] = None
    threshold_resolution_id: Optional[str] = None
    threshold_resolution_fingerprint: Optional[str] = None
    certification_id: Optional[str] = None
    certification_status: Optional[str] = None
    certification_score: Optional[float] = None
    explanation_id: Optional[str] = None

    # Telemetry and Execution Context
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    """Consolidated production response returned by the canonical V2 workflow engine."""
    model_config = ConfigDict(extra="ignore")

    workflow_run_id: str
    application_id: str
    state: WorkflowState
    status: str
    certified: bool = False
    equivalence_score: Optional[float] = None
    artifact_id: Optional[str] = None
    artifact_hash: Optional[str] = None
    threshold_resolution_id: Optional[str] = None
    threshold_resolution_fingerprint: Optional[str] = None
    unique_input_count: Optional[int] = None
    regressions_count: int = 0
    regressions: list[dict[str, Any]] = Field(default_factory=list)
    explanation: Optional[dict[str, Any]] = None
    audit_status: str = "PERSISTED"
    error_code: Optional[WorkflowErrorCode] = None
    error_message: Optional[str] = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
