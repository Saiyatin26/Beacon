"""BEACON V2 — Phase 6 Rule / Invariant Discovery Data Models & Policy.

Defines the domain-agnostic taxonomy of discovered rule candidates, deterministic discovery policies,
normalized observation matrix structures, candidate validation statuses, and complete discovery results.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class DiscoveredRuleType(str, Enum):
    """Domain-independent taxonomy of discovered behavioral rules and invariants."""
    INPUT_OUTPUT_RELATION = "INPUT_OUTPUT_RELATION"
    OUTPUT_CONSISTENCY = "OUTPUT_CONSISTENCY"
    ERROR_BEHAVIOR = "ERROR_BEHAVIOR"
    STATE_INVARIANT = "STATE_INVARIANT"
    STATE_TRANSITION = "STATE_TRANSITION"
    WORKFLOW_INVARIANT = "WORKFLOW_INVARIANT"
    CROSS_INPUT_INVARIANT = "CROSS_INPUT_INVARIANT"
    RELATIONAL_INVARIANT = "RELATIONAL_INVARIANT"
    BOUNDARY_BEHAVIOR = "BOUNDARY_BEHAVIOR"
    NULLABILITY_PATTERN = "NULLABILITY_PATTERN"
    TYPE_SHAPE_INVARIANT = "TYPE_SHAPE_INVARIANT"


class CandidateValidationStatus(str, Enum):
    """Empirical validation status of a discovered candidate hypothesis across observed evidence."""
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    WEAK = "WEAK"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    INCONCLUSIVE = "INCONCLUSIVE"


class ValidationScope(str, Enum):
    """Scope of candidate evaluation: per-fact atomic check or cross-observation group analysis."""
    PER_FACT = "PER_FACT"
    CROSS_OBSERVATION = "CROSS_OBSERVATION"


class DiscoveryMethod(str, Enum):
    """Deterministic mining strategy used to discover the candidate."""
    DIRECT_RELATION = "direct_relation"
    FREQUENCY_PATTERN = "frequency_pattern"
    STRUCTURAL_INVARIANT = "structural_invariant"
    STATE_DELTA_ANALYSIS = "state_delta_analysis"
    SEQUENCE_MINING = "sequence_mining"
    BOUNDARY_ANALYSIS = "boundary_analysis"
    CROSS_INPUT_ANALYSIS = "cross_input_analysis"
    TYPE_SHAPE_ANALYSIS = "type_shape_analysis"
    RELATIONAL_ANALYSIS = "relational_analysis"
    ERROR_ANALYSIS = "error_analysis"


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


class DiscoveryPolicy(BaseModel):
    """Deterministic configuration governing Phase 6 candidate generation, pruning, and validation."""
    model_config = ConfigDict(extra="ignore")

    minimum_support_count: int = 2
    minimum_support_ratio: float = 0.8
    minimum_confidence: float = 0.8
    maximum_candidate_complexity: int = 3
    maximum_fields_per_candidate: int = 5
    maximum_sequence_length: int = 10
    maximum_candidates: int = 100
    numeric_tolerance: float = 1e-6
    enable_formula_discovery: bool = True
    enable_sequence_discovery: bool = True
    enable_boundary_discovery: bool = True
    enable_state_discovery: bool = True
    policy_version: str = "1.0.0"

    def compute_policy_hash(self) -> str:
        """Computes a deterministic SHA-256 fingerprint of the policy configuration."""
        d = {
            "minimum_support_count": self.minimum_support_count,
            "minimum_support_ratio": self.minimum_support_ratio,
            "minimum_confidence": self.minimum_confidence,
            "maximum_candidate_complexity": self.maximum_candidate_complexity,
            "maximum_fields_per_candidate": self.maximum_fields_per_candidate,
            "maximum_sequence_length": self.maximum_sequence_length,
            "maximum_candidates": self.maximum_candidates,
            "numeric_tolerance": self.numeric_tolerance,
            "enable_formula_discovery": self.enable_formula_discovery,
            "enable_sequence_discovery": self.enable_sequence_discovery,
            "enable_boundary_discovery": self.enable_boundary_discovery,
            "enable_state_discovery": self.enable_state_discovery,
            "policy_version": self.policy_version,
        }
        return compute_deterministic_hash(d)


class DiscoveredCandidate(BaseModel):
    """A discovered candidate behavioral hypothesis backed by empirical observation provenance."""
    model_config = ConfigDict(extra="ignore")

    discovery_id: str = ""
    candidate_id: str = ""
    rule_type: DiscoveredRuleType
    canonical_expression: str
    normalized_expression: str
    description: str
    variables: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)

    # Empirical Statistics
    support_count: int = 0
    observation_count: int = 0
    applicable_count: int = 0
    contradiction_count: int = 0
    unknown_count: int = 0
    support_ratio: float = 0.0
    confidence: float = 0.0
    complexity: int = 1

    validation_status: CandidateValidationStatus = CandidateValidationStatus.CANDIDATE
    evidence_ids: list[str] = Field(default_factory=list)
    input_ids: list[str] = Field(default_factory=list)
    role_scope: str = "reference"  # "reference", "target", "both"

    provenance: dict[str, Any] = Field(default_factory=dict)
    discovery_method: DiscoveryMethod = DiscoveryMethod.DIRECT_RELATION
    policy_version: str = "1.0.0"
    fingerprint: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_fingerprint(self) -> str:
        """Computes a deterministic SHA-256 fingerprint over semantic rule type, expression, variables, and fields."""
        payload = {
            "rule_type": self.rule_type.value,
            "canonical_expression": self.canonical_expression.strip(),
            "variables": sorted(self.variables),
            "source_fields": sorted(self.source_fields),
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", self.compute_fingerprint())


class DiscoveryDiagnostic(BaseModel):
    """Structured diagnostic record detailing generator execution status, warnings, or failures."""
    model_config = ConfigDict(extra="ignore")

    generator_name: str
    status: str = "SUCCESS"  # "SUCCESS", "PARTIAL", "FAILED", "SKIPPED"
    severity: str = "INFO"   # "INFO", "WARNING", "ERROR"
    message: str = ""
    exception_type: Optional[str] = None
    candidate_count: int = 0
    evidence_scope: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ObservationFact(BaseModel):
    """Normalized atomic behavioral observation extracted from Phase 3 evidence for a single input & role."""
    model_config = ConfigDict(extra="ignore")

    input_id: str
    role: str  # "reference" or "target"
    evidence_ids: list[str] = Field(default_factory=list)

    # Scoped Observation Zones
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    raw_output: Optional[Any] = None
    exit_code: Optional[int] = None
    http_status: Optional[int] = None
    has_error: Optional[bool] = None  # None = not observed / unknown
    error_data: dict[str, Any] = Field(default_factory=dict)

    # Observation Presence Flags (Protects against model default assumptions)
    output_observed: bool = False
    error_observed: bool = False
    state_observed: bool = False

    # State Observations (Contract-locked)
    state_before: Optional[dict[str, Any]] = None
    state_after: Optional[dict[str, Any]] = None
    state_mutated: Optional[bool] = None
    state_valid: bool = False

    # Workflow Events
    workflow_events: list[str] = Field(default_factory=list)
    metadata_data: dict[str, Any] = Field(default_factory=dict)

    capture_status: str = "CAPTURED"
    is_valid: bool = True
    adaptation_failure: Optional[str] = None


class ObservationMatrix(BaseModel):
    """Complete collection of normalized observation facts organized by input_id and role."""
    model_config = ConfigDict(extra="ignore")

    session_id: str
    application_id: str
    reference_facts: list[ObservationFact] = Field(default_factory=list)
    target_facts: list[ObservationFact] = Field(default_factory=list)
    total_inputs: int = 0
    extracted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DiscoveryResult(BaseModel):
    """Top-level immutable container for Phase 6 discovered candidate rules and invariants."""
    model_config = ConfigDict(extra="ignore")

    discovery_id: str
    application_id: str
    session_id: str
    policy: DiscoveryPolicy
    policy_hash: str = ""
    candidates: list[DiscoveredCandidate] = Field(default_factory=list)

    # Completeness & Diagnostics
    overall_status: str = "COMPLETE"  # "COMPLETE", "PARTIAL", "FAILED"
    persistence_status: str = "NOT_REQUESTED"  # "NOT_REQUESTED", "PERSISTED", "FAILED"
    diagnostics: list[DiscoveryDiagnostic] = Field(default_factory=list)
    has_failures: bool = False
    has_warnings: bool = False

    evidence_scope: dict[str, Any] = Field(default_factory=dict)
    observation_count: int = 0
    generated_count: int = 0
    validated_count: int = 0
    contradicted_count: int = 0
    inconclusive_count: int = 0
    common_fingerprints: list[str] = Field(default_factory=list)
    result_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def reference_candidates(self) -> list[DiscoveredCandidate]:
        """Returns discovered candidates scoped to the Reference application."""
        return [c for c in self.candidates if c.role_scope == "reference"]

    @property
    def target_candidates(self) -> list[DiscoveredCandidate]:
        """Returns discovered candidates scoped to the Target application."""
        return [c for c in self.candidates if c.role_scope == "target"]

    def compute_result_hash(self) -> str:
        """Computes deterministic SHA-256 digest across all ordered candidate fingerprints and validation metrics."""
        ordered_candidates = [
            {
                "candidate_id": c.candidate_id,
                "fingerprint": c.fingerprint,
                "rule_type": c.rule_type.value,
                "canonical_expression": c.canonical_expression,
                "role_scope": c.role_scope,
                "support_count": c.support_count,
                "contradiction_count": c.contradiction_count,
                "unknown_count": c.unknown_count,
                "applicable_count": c.applicable_count,
                "confidence": c.confidence,
                "validation_status": c.validation_status.value,
            }
            for c in sorted(self.candidates, key=lambda x: (x.fingerprint, x.role_scope, x.candidate_id))
        ]
        payload = {
            "application_id": self.application_id,
            "session_id": self.session_id,
            "policy_hash": self.policy_hash,
            "observation_count": self.observation_count,
            "candidates": ordered_candidates,
            "common_fingerprints": sorted(self.common_fingerprints),
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.policy_hash:
            object.__setattr__(self, "policy_hash", self.policy.compute_policy_hash())
        if not self.result_hash:
            object.__setattr__(self, "result_hash", self.compute_result_hash())
        if any(d.status == "FAILED" or d.severity == "ERROR" for d in self.diagnostics):
            object.__setattr__(self, "has_failures", True)
            if self.overall_status == "COMPLETE":
                object.__setattr__(self, "overall_status", "PARTIAL")
