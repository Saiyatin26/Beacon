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
    deviation: Optional[float] = None  # Normalized deviation d_{di} in [0, 1]
    agreement: Optional[float] = None  # Agreement a_{di} = 1 - d_{di} in [0, 1]
    details: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.status and not self.verdict:
            object.__setattr__(self, "verdict", self.status)
        elif self.verdict and not self.status:
            object.__setattr__(self, "status", self.verdict)
        if self.deviation is not None and self.agreement is None:
            object.__setattr__(self, "agreement", max(0.0, min(1.0, 1.0 - self.deviation)))
        elif self.agreement is not None and self.deviation is None:
            object.__setattr__(self, "deviation", max(0.0, min(1.0, 1.0 - self.agreement)))


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
    mean_deviation: Optional[float] = None  # MeanDeviation_d = (1 / N_d) * sum(d_di)
    dimension_score: Optional[float] = None  # DimensionScore_d = 1 - MeanDeviation_d
    is_available: bool = True  # If N_d == 0, dimension is marked unavailable (not score 1)


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
    observed_deviation: Optional[float] = None  # Aggregated deviation for this input in [0, 1]
    agreement: Optional[float] = None  # Aggregated agreement = 1 - observed_deviation
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

    # Dynamic Behavioral Scoring Normative Contract (Patent-Facing Spec)
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    behavioral_score: float = 1.0  # Dynamic Behavioral Score in [0.0, 1.0]
    observed_deviation: float = 0.0  # 1.0 - behavioral_score
    percentage_score: float = 100.0  # 100.0 * behavioral_score
    scoring_weights: dict[str, float] = Field(default_factory=dict)
    coverage: float = 1.0  # ObservedComparableCells / RequiredComparableCells

    @property
    def divergent_inputs(self) -> int:
        return self.different_inputs


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


def compute_evaluation_result_hash(eval_res: EvaluationResult) -> str:
    """Computes deterministic canonical SHA-256 fingerprint over all material behavioral evaluation findings."""
    diff_inputs = getattr(eval_res.summary, "different_inputs", getattr(eval_res.summary, "divergent_inputs", 0))
    beh_score = getattr(eval_res.summary, "behavioral_score", 1.0)
    obs_dev = getattr(eval_res.summary, "observed_deviation", 0.0)
    cov = getattr(eval_res.summary, "coverage", 1.0)
    material_data = {
        "evaluation_id": eval_res.evaluation_id,
        "bundle_id": eval_res.bundle_id or "",
        "application_id": eval_res.application_id or "",
        "verdict": eval_res.verdict.value if hasattr(eval_res.verdict, "value") else str(eval_res.verdict),
        "policy_id": eval_res.policy_id,
        "policy_hash": eval_res.policy_hash,
        "total_inputs": eval_res.summary.total_inputs,
        "equivalent_inputs": eval_res.summary.equivalent_inputs,
        "different_inputs": diff_inputs,
        "total_differences": eval_res.summary.total_differences,
        "behavioral_score": round(float(beh_score), 6),
        "observed_deviation": round(float(obs_dev), 6),
        "coverage": round(float(cov), 6),
        "input_results": [
            {
                "input_id": item.input_id,
                "verdict": item.verdict.value if hasattr(item.verdict, "value") else str(item.verdict),
                "diff_count": len(item.differences),
            }
            for item in sorted(eval_res.input_results, key=lambda x: x.input_id)
        ],
    }
    canonical_json = json.dumps(material_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_evaluation_result_integrity(eval_res: EvaluationResult) -> bool:
    """Confirms cryptographic integrity of an EvaluationResult against its canonical content hash."""
    if not eval_res or not eval_res.evaluation_id:
        return False
    expected_hash = compute_evaluation_result_hash(eval_res)
    if not eval_res.evaluation_hash:
        return True
    return eval_res.evaluation_hash == expected_hash
