"""BEACON V2 — Phase 4 Behavioral Evaluation Models & Data Contracts.

Defines domain-agnostic data structures for evaluating behavioral equivalence
between Reference and Target executions based on Phase 3 evidence.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class EvaluationVerdict(str, Enum):
    """Deterministic behavioral evaluation verdict vocabulary."""
    EQUIVALENT = "EQUIVALENT"
    DIFFERENT = "DIFFERENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


# Alias for compatibility with project naming conventions
EvaluationStatus = EvaluationVerdict


class BehaviorDimension(str, Enum):
    """Core observable behavioral dimensions evaluated in Phase 4."""
    OUTPUT = "OUTPUT"
    ERROR = "ERROR"
    BOUNDARY = "BOUNDARY"
    STATE = "STATE"
    WORKFLOW = "WORKFLOW"
    NONFUNCTIONAL = "NONFUNCTIONAL"


class DifferenceType(str, Enum):
    """Authoritative taxonomy of behavioral differences detected during evaluation."""
    # Output differences
    OUTPUT_VALUE_MISMATCH = "OUTPUT_VALUE_MISMATCH"
    MISSING_FIELD = "MISSING_FIELD"
    EXTRA_FIELD = "EXTRA_FIELD"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    ARRAY_ORDER_MISMATCH = "ARRAY_ORDER_MISMATCH"
    ARRAY_LENGTH_MISMATCH = "ARRAY_LENGTH_MISMATCH"
    NUMERIC_TOLERANCE_EXCEEDED = "NUMERIC_TOLERANCE_EXCEEDED"
    STRING_MISMATCH = "STRING_MISMATCH"
    NULL_VS_MISSING_MISMATCH = "NULL_VS_MISSING_MISMATCH"

    # Error behavior differences
    SUCCESS_ERROR_MISMATCH = "SUCCESS_ERROR_MISMATCH"
    ERROR_STATUS_MISMATCH = "ERROR_STATUS_MISMATCH"
    ERROR_CODE_MISMATCH = "ERROR_CODE_MISMATCH"
    ERROR_MESSAGE_MISMATCH = "ERROR_MESSAGE_MISMATCH"
    ERROR_CATEGORY_MISMATCH = "ERROR_CATEGORY_MISMATCH"
    EXCEPTION_TYPE_MISMATCH = "EXCEPTION_TYPE_MISMATCH"

    # Boundary differences
    BOUNDARY_BEHAVIOR_MISMATCH = "BOUNDARY_BEHAVIOR_MISMATCH"

    # State & Side-effect differences
    STATE_DELTA_MISMATCH = "STATE_DELTA_MISMATCH"
    DATABASE_MUTATION_MISMATCH = "DATABASE_MUTATION_MISMATCH"
    DATABASE_ROW_COUNT_MISMATCH = "DATABASE_ROW_COUNT_MISMATCH"
    FILESYSTEM_DELTA_MISMATCH = "FILESYSTEM_DELTA_MISMATCH"
    HTTP_SIDE_EFFECT_MISMATCH = "HTTP_SIDE_EFFECT_MISMATCH"

    # Workflow differences
    WORKFLOW_ORDER_MISMATCH = "WORKFLOW_ORDER_MISMATCH"
    WORKFLOW_SEQUENCE_MISMATCH = "WORKFLOW_SEQUENCE_MISMATCH"

    # Nonfunctional differences
    NONFUNCTIONAL_THRESHOLD_EXCEEDED = "NONFUNCTIONAL_THRESHOLD_EXCEEDED"

    # Evidence & Execution differences
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_CORRUPTED = "EVIDENCE_CORRUPTED"
    UNMATCHED_EXECUTION = "UNMATCHED_EXECUTION"
    EXTRA_TARGET_EXECUTION = "EXTRA_TARGET_EXECUTION"


class BehaviorDifference(BaseModel):
    """Structured, audit-ready record of a single detected behavioral difference."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    difference_id: str = Field(
        default_factory=lambda: f"DIFF-{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:12]}"
    )
    dimension: BehaviorDimension
    input_id: str
    difference_type: DifferenceType
    field_path: Optional[str] = None
    reference_value: Optional[Any] = None
    target_value: Optional[Any] = None
    reference_evidence_id: Optional[str] = None
    target_evidence_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    comparison_method: str = "exact"
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DimensionResult(BaseModel):
    """Evaluation outcome for a single behavioral dimension."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dimension: BehaviorDimension
    status: EvaluationVerdict
    verdict: EvaluationVerdict
    reference_value: Optional[Any] = None
    target_value: Optional[Any] = None
    comparison_method: str = "default"
    difference_type: Optional[DifferenceType] = None
    differences: list[BehaviorDifference] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.status and not self.verdict:
            object.__setattr__(self, "verdict", self.status)
        elif self.verdict and not self.status:
            object.__setattr__(self, "status", self.verdict)


class DimensionEvaluationSummary(BaseModel):
    """Statistical summary of evaluations for a specific dimension."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dimension: BehaviorDimension
    total_evaluated: int = 0
    equivalent_count: int = 0
    different_count: int = 0
    inconclusive_count: int = 0
    not_applicable_count: int = 0
    overall_verdict: EvaluationVerdict = EvaluationVerdict.NOT_APPLICABLE


class InputEvaluationResult(BaseModel):
    """Complete evaluation outcome for a single canonical input item."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    input_id: str
    verdict: EvaluationVerdict
    status: EvaluationVerdict
    dimension_results: dict[BehaviorDimension, DimensionResult] = Field(default_factory=dict)
    differences: list[BehaviorDifference] = Field(default_factory=list)
    boundary_category: Optional[str] = None
    reference_evidence_ids: list[str] = Field(default_factory=list)
    target_evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def overall_verdict(self) -> EvaluationVerdict:
        return self.verdict

    @property
    def overall_status(self) -> EvaluationVerdict:
        return self.status


class EvaluationSummary(BaseModel):
    """Statistical rollup and summary of an evaluation across all inputs."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_inputs: int = 0
    evaluated_inputs: int = 0
    equivalent_inputs: int = 0
    different_inputs: int = 0
    inconclusive_inputs: int = 0
    error_inputs: int = 0
    not_applicable_inputs: int = 0
    overall_verdict: EvaluationVerdict = EvaluationVerdict.INCONCLUSIVE
    dimension_summaries: dict[BehaviorDimension, DimensionEvaluationSummary] = Field(default_factory=dict)
    total_differences: int = 0
    differences_by_type: dict[str, int] = Field(default_factory=dict)
    differences_by_dimension: dict[str, int] = Field(default_factory=dict)
    coverage_ratio: float = 1.0


class EvaluationResult(BaseModel):
    """Complete evaluation outcome for a full execution run or EvidenceBundle."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    evaluation_id: str
    bundle_id: Optional[str] = None
    application_id: Optional[str] = None
    timestamp: Union[datetime, str] = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    verdict: EvaluationVerdict = EvaluationVerdict.INCONCLUSIVE
    status: EvaluationVerdict = EvaluationVerdict.INCONCLUSIVE
    policy_id: str = "default_v2"
    policy_hash: str = ""
    summary: EvaluationSummary = Field(default_factory=EvaluationSummary)
    input_results: list[InputEvaluationResult] = Field(default_factory=list)
    differences: list[BehaviorDifference] = Field(default_factory=list)
    bundle_hash: Optional[str] = None
    evaluation_hash: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def overall_verdict(self) -> EvaluationVerdict:
        return self.verdict

    @property
    def overall_status(self) -> EvaluationVerdict:
        return self.status

    @property
    def total_inputs(self) -> int:
        return self.summary.total_inputs

    @property
    def evaluated_inputs(self) -> int:
        return self.summary.evaluated_inputs

    @property
    def total_differences(self) -> int:
        return self.summary.total_differences


# Aliases for backward/alternate naming compatibility
EvaluationSession = EvaluationResult
BatchEvaluationResult = EvaluationResult


class EvaluationRequest(BaseModel):
    """Payload to trigger behavioral evaluation on a Phase 3 execution session or bundle."""
    execution_session_id: Optional[str] = None
    bundle_id: Optional[str] = None
    comparison_policy: Optional[dict[str, Any]] = None
    comparison_policy_id: Optional[str] = None
    enabled_dimensions: Optional[list[BehaviorDimension]] = None
    fail_fast: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
