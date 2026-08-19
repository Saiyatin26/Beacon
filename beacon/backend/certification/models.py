"""Phase 9 — Cross-Version Behavioral Equivalence Domain Models.

Defines observation data contracts, shared test inputs, comparison records,
regression counterexamples, and full certification reports.
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from oracle.models import OracleEvaluationReport


class Observation(BaseModel):
    """Execution observation of a target implementation on a single input."""
    input_id: str
    raw_inputs: dict[str, Any]
    normalized_inputs: dict[str, Any]
    raw_outputs: dict[str, Any]
    normalized_outputs: dict[str, Any]
    execution_status: Literal["SUCCESS", "EXCEPTION", "TIMEOUT"] = "SUCCESS"
    implementation_name: str
    implementation_version: str = "1.0.0"
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class CertificationTestInput(BaseModel):
    """Shared test input with provenance and origin metadata."""
    input_id: str
    values: dict[str, Any]
    origin: Literal[
        "boundary_probe",
        "near_boundary_probe",
        "diverse_sampling",
        "runtime_trace",
        "counterexample",
        "explicit_case",
    ] = "diverse_sampling"
    provenance: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class BehavioralRegression(BaseModel):
    """Concrete behavioral regression counterexample produced during certification."""
    regression_id: str
    oracle_id: str
    oracle_version: int = 1
    input_id: str
    input_values: dict[str, Any]
    expected_behavior: Any
    legacy_output: Any
    modern_output: Any
    failed_assertion: str
    legacy_version: str = "1.0.0"
    modern_version: str = "2.0.0"
    severity: str = "medium"
    domain: str = "business_logic"
    confidence: float = 1.0
    timestamp: str = ""


class ComparisonRecord(BaseModel):
    """Audit record capturing the side-by-side comparison of legacy and modern executions on one input."""
    comparison_id: str
    oracle_id: str
    oracle_version: int = 1
    oracle_set_hash: str = ""
    input_id: str
    input_values: dict[str, Any]
    legacy_observation: Observation
    modern_observation: Observation
    legacy_eval_report: OracleEvaluationReport
    modern_eval_report: OracleEvaluationReport
    equivalence_outcome: Literal[
        "MATCH_PASS",
        "MODERN_REGRESSION",
        "REFERENCE_INCONSISTENT",
        "MUTUAL_VIOLATION",
        "NOT_APPLICABLE",
        "EXECUTION_ERROR",
    ]
    timestamp: str = ""


class OracleEquivalenceMetrics(BaseModel):
    """Probe-level behavioral metrics for a single oracle."""
    oracle_id: str
    total_probes: int = 0
    applicable_probes: int = 0
    legacy_passes: int = 0
    modern_passes: int = 0
    modern_regressions: int = 0
    reference_inconsistencies: int = 0
    mutual_violations: int = 0
    execution_errors: int = 0
    not_applicable: int = 0
    oracle_equivalence_rate: float = 1.0


class CrossVersionCertificationReport(BaseModel):
    """Complete, language-independent Cross-Version Behavioral Equivalence Certification Report."""
    certification_id: str
    timestamp: str
    oracle_set_id: str = ""
    oracle_set_hash: str = ""
    legacy_version: str = "1.0.0"
    modern_version: str = "2.0.0"
    overall_equivalence_score: float = 0.0
    domain_scores: dict[str, float] = Field(default_factory=dict)
    oracle_metrics: dict[str, OracleEquivalenceMetrics] = Field(default_factory=dict)
    regressions: list[BehavioralRegression] = Field(default_factory=list)
    reference_inconsistencies: list[dict[str, Any]] = Field(default_factory=list)
    comparison_records: list[ComparisonRecord] = Field(default_factory=list)
    total_probes: int = 0
    total_applicable_probes: int = 0
    total_regressions: int = 0
    total_reference_inconsistencies: int = 0
    certified: bool = False
    statement: str = (
        "This report measures behavioral equivalence relative to the frozen validated oracle set "
        "and tested input domain. It does not constitute a formal mathematical proof of arbitrary program equivalence."
    )
