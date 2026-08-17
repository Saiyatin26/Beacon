"""Shared data contracts between stages. Keeping these in one place is what
makes the six stages independently swappable — Stage 3 only needs to know the
shape of an Invariant, not how Stage 2 produced it."""

from __future__ import annotations
from typing import Literal, Optional, Any
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
    condition: str          # human/DSL-readable, e.g. "credit_score < 600 AND debt_ratio > 0.4"
    consequence: str        # e.g. "reject"
    source_lines: list[int] = Field(default_factory=list)
    severity: Severity = "medium"


class EvidenceReport(BaseModel):
    """Stage 2b output."""
    invariant_id: str
    evidence_count: int
    evidence_count_norm: float
    input_diversity: float


class ValidationReport(BaseModel):
    """Stage 2c output."""
    invariant_id: str
    boundary_pass_rate: float
    contradiction_count: int
    counterexamples: list[dict] = Field(default_factory=list)


class ValidatedInvariant(BaseModel):
    """Stage 2d output — the unit that graduates (or doesn't) to Stage 3."""
    invariant_id: str
    condition: str
    consequence: str
    severity: Severity
    confidence: float
    graduated: bool  # confidence >= settings.confidence_threshold


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
    """Stage 5 output, persisted to drift_samples_col."""
    run_timestamp: str
    equivalence_score: float
    baseline_score: float
    delta_pct: float
    alert: bool


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

