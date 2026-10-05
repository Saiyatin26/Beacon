"""Shared data contracts between stages. Keeping these in one place is what
makes the six stages independently swappable — Stage 3 only needs to know the
shape of an Invariant, not how Stage 2 produced it."""

from __future__ import annotations
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]


class TraceEvent(BaseModel):
    """One row of Stage 1 output: a single observed execution."""
    inputs: dict
    output: dict = Field(default_factory=dict)
    branch_path: list[str] = Field(default_factory=list)
    db_reads: list[dict] = Field(default_factory=list)
    db_writes: list[dict] = Field(default_factory=list)
    execution_id: Optional[str] = None
    timestamp: Optional[str] = None
    function: Optional[str] = None
    executed_branches: list[dict] = Field(default_factory=list)
    variable_states: list[dict] = Field(default_factory=list)
    exception: Optional[str] = None



class CandidateInvariant(BaseModel):
    """Stage 2a output — before evidence/validation/confidence scoring."""
    invariant_id: str
    condition: str          # canonical normalized DSL-readable expression
    consequence: str        # e.g. "REJECT"
    raw_condition: Optional[str] = None  # original unnormalized condition (e.g. from LLM)
    source_file: str = ""
    source_lines: list[int] = Field(default_factory=list)
    severity: Severity = "medium"
    evidence_ids: list[str] = Field(default_factory=list)
    execution_ids: list[str] = Field(default_factory=list)
    generation_method: str = "offline"  # "offline" or "llm"
    timestamp: str = ""
    rationale: Optional[str] = None
    domain: str = "business_logic"
    confidence: float = 0.0
    confidence_components: dict[str, Any] = Field(default_factory=dict)
    grounding_result: Optional[dict] = None
    validation_result: Optional[Union[dict, Any]] = None
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    status: str = "candidate"


class UnconfirmedCandidate(CandidateInvariant):
    """Stage 2 output for candidates that failed the confidence gate."""
    confidence: float
    graduated: bool = False
    status: str = "unconfirmed"


class EvidenceReport(BaseModel):
    """Stage 2b output."""
    invariant_id: str
    evidence_count: int
    evidence_count_norm: float
    input_diversity: float
    matching_execution_ids: list[str] = Field(default_factory=list)
    static_evidence_ids: list[str] = Field(default_factory=list)
    dynamic_evidence_ids: list[str] = Field(default_factory=list)


class Counterexample(BaseModel):
    """Detailed counterexample representing a concrete input violating the invariant candidate."""
    candidate_id: str = ""
    validation_run_id: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    condition_result: bool = True
    expected_result: str = ""
    actual_result: str = ""
    failure_type: str = "VIOLATION"  # VIOLATION | EXECUTION_ERROR | CONTRADICTION
    evidence_ids: list[str] = Field(default_factory=list)
    execution_ids: list[str] = Field(default_factory=list)
    timestamp: str = ""


class ValidationReport(BaseModel):
    """Stage 2c output — comprehensive adversarial validation report."""
    invariant_id: str
    validation_run_id: str = ""
    overall_property_pass_rate: float = 0.0
    boundary_pass_rate: float = 0.0
    diverse_input_pass_rate: float = 0.0
    contradiction_count: int = 0
    counterexamples: list[dict] = Field(default_factory=list)
    condition_true_count: int = 0
    condition_false_count: int = 0
    total_probes: int = 0
    passed_probes: int = 0
    failed_probes: int = 0
    execution_errors: int = 0
    boundary_tests_count: int = 0
    boundary_probes_total: int = 0
    boundary_probes_true: int = 0
    boundary_probes_passed: int = 0
    boundary_probes_failed: int = 0
    diverse_tests_count: int = 0
    diverse_probes_total: int = 0
    diverse_probes_true: int = 0
    diverse_probes_passed: int = 0
    diverse_probes_failed: int = 0
    condition_coverage: float = 0.0
    contradiction_details: list[dict] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    execution_ids: list[str] = Field(default_factory=list)
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
    status: str = "VALIDATED"  # VALIDATED | INVALIDATED | UNCONFIRMED


class ValidatedInvariant(CandidateInvariant):
    """Stage 2d output — the unit that graduates (or doesn't) to Stage 3."""
    confidence: float
    graduated: bool = True  # confidence >= settings.confidence_threshold
    status: str = "graduated"


class Oracle(BaseModel):
    """Stage 3 output — language-agnostic executable schema."""
    invariant_id: str
    inputs: list[str]
    property: str            # DSL expression evaluated by oracle/interpreter.py
    tolerance: float = 0.0
    confidence: float
    severity: Severity


class Violation(BaseModel):
    """Stage 4 per-invariant failure detail."""
    invariant_id: str
    expected: str
    legacy_output: str
    modern_output: str
    counterexample: dict
    confidence: float
    severity: Severity


class CertificationRun(BaseModel):
    """Stage 4 output, persisted to certification_runs_col."""
    run_id: str
    timestamp: str
    equivalence_score: float
    domain_scores: dict[str, float] = Field(default_factory=dict)
    violations: list[Violation] = Field(default_factory=list)
    total_checked: int
    total_violated: int


class DriftSample(BaseModel):
    """Continuous Drift Monitoring sample with benchmark identity and baseline tracking."""
    run_timestamp: str
    equivalence_score: float
    baseline_score: float = 1.0
    delta_pct: float = 0.0
    alert: bool = False
    benchmark_id: Optional[str] = None
    benchmark_version: Optional[str] = "1.0.0"
    certification_run_id: Optional[str] = None
    oracle_set_id: Optional[str] = None
    oracle_set_hash: Optional[str] = None
    policy_id: Optional[str] = "POL-DEFAULT"


# Stage 1 — Static Analysis Evidence Models (Phase 3)

class SourceLocation(BaseModel):
    file: str = ""
    line: int = 0
    column: Optional[int] = None
    function: Optional[str] = None


class ComparisonFact(BaseModel):
    left: str
    operator: str
    right: Any
    location: SourceLocation


class ConditionFact(BaseModel):
    expression: str
    logical_operator: Optional[str] = None  # "AND", "OR", "NOT", or None
    comparisons: list[ComparisonFact] = Field(default_factory=list)
    sub_conditions: list[ConditionFact] = Field(default_factory=list)
    location: SourceLocation
    outcome: Optional[str] = None


class AssignmentFact(BaseModel):
    target: str
    value: Any
    location: SourceLocation


class ReturnFact(BaseModel):
    value: str
    location: SourceLocation


class FunctionCallFact(BaseModel):
    function_name: str
    arguments: list[str] = Field(default_factory=list)
    location: SourceLocation


class FunctionFact(BaseModel):
    name: str
    parameters: list[str] = Field(default_factory=list)
    location: SourceLocation


class StaticAnalysisResult(BaseModel):
    file: str
    language: str
    functions: list[FunctionFact] = Field(default_factory=list)
    conditions: list[ConditionFact] = Field(default_factory=list)
    comparisons: list[ComparisonFact] = Field(default_factory=list)
    assignments: list[AssignmentFact] = Field(default_factory=list)
    returns: list[ReturnFact] = Field(default_factory=list)
    calls: list[FunctionCallFact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

