"""BEACON V2 — Phase 8 Dynamic / Evidence-Driven Thresholds Domain Models.

Defines the core data models for threshold policies, resolution records,
difference metrics, and advanced behavioral evaluation results.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from evaluation.models import BehaviorDimension, DifferenceType, EvaluationVerdict


class ThresholdStrategy(str, Enum):
    """Supported threshold calculation strategies."""
    FIXED = "FIXED"                      # Explicit fixed tolerance value
    ABSOLUTE = "ABSOLUTE"                # Absolute numerical difference (|target - reference| <= tol)
    RELATIVE = "RELATIVE"                # Relative numerical difference (|target - reference| / |reference| <= tol)
    PERCENTAGE = "PERCENTAGE"            # Percentage numerical difference (|target - reference| / |reference| * 100 <= tol)
    STATISTICAL = "STATISTICAL"          # Statistical tolerance based on variance / stddev / IQR
    EVIDENCE_DERIVED = "EVIDENCE_DERIVED"# Derived from historical / reference evidence variation


class ThresholdStatus(str, Enum):
    """Explicit status of a threshold resolution operation."""
    RESOLVED = "RESOLVED"                          # Successfully resolved and bounded
    FIXED = "FIXED"                                # Derived directly from static fixed configuration
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"# Evidence sample size below minimum threshold
    INVALID_POLICY = "INVALID_POLICY"              # Policy configuration is malformed or invalid
    INVALID_EVIDENCE = "INVALID_EVIDENCE"          # Evidence data corrupted or incompatible
    UNAVAILABLE = "UNAVAILABLE"                    # No threshold policy or evidence available
    ERROR = "ERROR"                                # Unexpected calculation or execution error


class EstimatorType(str, Enum):
    """Mathematical / statistical estimators for evidence-derived variance."""
    MEAN_STDDEV = "MEAN_STDDEV"              # k * standard deviation from mean
    IQR_ROBUST = "IQR_ROBUST"                # k * Interquartile Range (Q3 - Q1)
    MAX_OBSERVED_DELTA = "MAX_OBSERVED_DELTA"# Maximum observed delta across reference samples
    PERCENTILE_95 = "PERCENTILE_95"          # 95th percentile delta
    RANGE_FRACTION = "RANGE_FRACTION"        # k * (max - min) range spread


class OutlierPolicy(str, Enum):
    """Explicit deterministic outlier handling strategy for evidence samples."""
    NONE = "NONE"          # No outlier handling; use all valid reference observations
    CLIPPED = "CLIPPED"    # Clip observations outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
    ROBUST = "ROBUST"      # Exclude observations outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]


class DifferenceMetric(str, Enum):
    """Taxonomy of difference metrics evaluated under dynamic thresholds."""
    ABSOLUTE_DIFF = "ABSOLUTE_DIFF"
    RELATIVE_DIFF = "RELATIVE_DIFF"
    PERCENTAGE_DIFF = "PERCENTAGE_DIFF"
    COUNT_DIFF = "COUNT_DIFF"
    LATENCY_DIFF = "LATENCY_DIFF"
    SEQUENCE_DISTANCE = "SEQUENCE_DISTANCE"
    STRUCTURAL_SIMILARITY = "STRUCTURAL_SIMILARITY"


def compute_deterministic_hash(data: Any) -> str:
    """Computes a deterministic SHA-256 digest of arbitrary structured data."""
    if isinstance(data, (dict, list)):
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    elif isinstance(data, str):
        canonical = data
    elif isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    else:
        canonical = str(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ThresholdPolicy(BaseModel):
    """Versioned specification governing how tolerance thresholds are resolved."""
    model_config = ConfigDict(extra="ignore")

    policy_id: str = "default_threshold_policy"
    version: str = "1.0.0"
    description: str = "Default deterministic threshold policy"
    metric: DifferenceMetric = DifferenceMetric.ABSOLUTE_DIFF
    strategy: ThresholdStrategy = ThresholdStrategy.FIXED
    
    # Parameters for the chosen strategy (e.g. {"value": 0.05} or {"k": 2.0})
    parameters: dict[str, Any] = Field(default_factory=dict)
    
    # Evidence-derived requirements
    minimum_samples: int = 5
    minimum_bound: Optional[float] = None
    maximum_bound: Optional[float] = None
    
    # Estimator and outlier controls
    estimator: EstimatorType = EstimatorType.MEAN_STDDEV
    outlier_policy: OutlierPolicy = OutlierPolicy.NONE
    
    # Explicit fallback controls when evidence is insufficient
    fallback_strategy: Optional[ThresholdStrategy] = None
    fallback_value: Optional[float] = None
    
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    def compute_policy_hash(self) -> str:
        """Computes a canonical SHA-256 fingerprint over semantic policy configuration."""
        payload = {
            "policy_id": self.policy_id,
            "version": self.version,
            "metric": self.metric.value,
            "strategy": self.strategy.value,
            "parameters": self.parameters,
            "minimum_samples": self.minimum_samples,
            "minimum_bound": self.minimum_bound,
            "maximum_bound": self.maximum_bound,
            "estimator": self.estimator.value,
            "outlier_policy": self.outlier_policy.value,
            "fallback_strategy": self.fallback_strategy.value if self.fallback_strategy else None,
            "fallback_value": self.fallback_value,
            "enabled": self.enabled,
        }
        return compute_deterministic_hash(payload)


class ThresholdResolution(BaseModel):
    """Immutable, auditable record of a resolved and frozen threshold decision."""
    model_config = ConfigDict(extra="ignore")

    resolution_id: str
    metric: DifferenceMetric
    strategy: ThresholdStrategy
    status: ThresholdStatus
    
    # Quantitative values
    raw_value: Optional[float] = None
    final_value: Optional[float] = None
    minimum_bound: Optional[float] = None
    maximum_bound: Optional[float] = None
    
    # Evidence & Estimator Provenance
    sample_count: int = 0
    minimum_required_samples: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    estimator: Optional[EstimatorType] = None
    outlier_policy: OutlierPolicy = OutlierPolicy.NONE
    outliers_detected: int = 0
    
    # Fallback traceability
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    
    # Policy Identity & Fingerprint
    policy_id: str
    policy_version: str
    policy_hash: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over semantic resolution fields."""
        payload = {
            "metric": self.metric.value,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "raw_value": self.raw_value,
            "final_value": self.final_value,
            "minimum_bound": self.minimum_bound,
            "maximum_bound": self.maximum_bound,
            "sample_count": self.sample_count,
            "minimum_required_samples": self.minimum_required_samples,
            "evidence_ids": sorted(self.evidence_ids),
            "estimator": self.estimator.value if self.estimator else None,
            "fallback_used": self.fallback_used,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", self.compute_fingerprint())


class AdvancedEvaluationDifference(BaseModel):
    """Detailed record of a behavioral difference evaluated under a dynamic threshold."""
    model_config = ConfigDict(extra="ignore")

    difference_id: str
    dimension: BehaviorDimension
    input_id: str
    difference_type: DifferenceType
    field_path: Optional[str] = None
    reference_value: Optional[Any] = None
    target_value: Optional[Any] = None
    observed_difference: Optional[float] = None
    resolved_threshold: Optional[float] = None
    resolution: Optional[ThresholdResolution] = None
    within_tolerance: bool = False
    verdict: EvaluationVerdict = EvaluationVerdict.DIFFERENT
    explanation: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AdvancedEvaluationRequest(BaseModel):
    """Input payload requesting advanced behavioral evaluation."""
    model_config = ConfigDict(extra="ignore")

    application_id: str
    oracle_set_id: Optional[str] = None
    reference_session_id: Optional[str] = None
    target_session_id: Optional[str] = None
    policy_id: Optional[str] = None
    custom_policy: Optional[ThresholdPolicy] = None
    persist: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdvancedEvaluationResult(BaseModel):
    """Frozen, auditable result of an advanced behavioral evaluation run."""
    model_config = ConfigDict(extra="ignore")

    evaluation_id: str
    application_id: str
    oracle_set_id: str
    oracle_set_hash: str = ""
    policy_id: str
    policy_version: str
    policy_hash: str = ""
    
    overall_verdict: EvaluationVerdict = EvaluationVerdict.INCONCLUSIVE
    status: str = "COMPLETE"
    
    # Dimension verdicts
    dimension_verdicts: dict[str, EvaluationVerdict] = Field(default_factory=dict)
    
    # Traceability & Details
    total_evaluations: int = 0
    passed_count: int = 0
    failed_count: int = 0
    inconclusive_count: int = 0
    
    resolutions: list[ThresholdResolution] = Field(default_factory=list)
    differences: list[AdvancedEvaluationDifference] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    
    result_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_result_hash(self) -> str:
        """Computes deterministic SHA-256 digest of final evaluation semantics."""
        ordered_diffs = [
            {
                "dimension": d.dimension.value,
                "input_id": d.input_id,
                "difference_type": d.difference_type.value,
                "field_path": d.field_path,
                "observed_difference": d.observed_difference,
                "resolved_threshold": d.resolved_threshold,
                "within_tolerance": d.within_tolerance,
                "verdict": d.verdict.value,
            }
            for d in sorted(self.differences, key=lambda x: (x.dimension.value, x.input_id, x.field_path or ""))
        ]
        ordered_res = [
            {
                "resolution_id": r.resolution_id,
                "metric": r.metric.value,
                "strategy": r.strategy.value,
                "status": r.status.value,
                "final_value": r.final_value,
                "sample_count": r.sample_count,
                "fingerprint": r.fingerprint,
            }
            for r in sorted(self.resolutions, key=lambda x: (x.metric.value, x.resolution_id))
        ]
        payload = {
            "application_id": self.application_id,
            "oracle_set_id": self.oracle_set_id,
            "oracle_set_hash": self.oracle_set_hash,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "overall_verdict": self.overall_verdict.value,
            "status": self.status,
            "dimension_verdicts": {k: v.value for k, v in sorted(self.dimension_verdicts.items())},
            "differences": ordered_diffs,
            "resolutions": ordered_res,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.result_hash:
            object.__setattr__(self, "result_hash", self.compute_result_hash())
