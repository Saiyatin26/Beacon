"""Phase 10 — Quantified Behavioral Equivalence Certification Models.

Defines observation contracts, shared test inputs, comparison records,
behavioral regressions, certification policy, metrics, per-oracle summaries,
and immutable cryptographic certification artifacts.
"""

from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field
from oracle.models import OracleEvaluationReport


class CertificationStatus(str, Enum):
    """Formal Certification Status outcomes under Policy."""
    CERTIFIED = "CERTIFIED"
    CERTIFIED_WITH_WARNINGS = "CERTIFIED_WITH_WARNINGS"
    NOT_CERTIFIED = "NOT_CERTIFIED"
    REFERENCE_INCONSISTENT = "REFERENCE_INCONSISTENT"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    ORACLE_SET_INVALID = "ORACLE_SET_INVALID"


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
    input_hash: str = ""
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

    def model_post_init(self, __context: Any) -> None:
        if not self.input_hash and self.values:
            canonical = json.dumps(self.values, sort_keys=True, separators=(",", ":"))
            object.__setattr__(self, "input_hash", hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16])


class BehavioralRegression(BaseModel):
    """Concrete behavioral regression counterexample produced during certification."""
    regression_id: str
    oracle_id: str
    oracle_version: int = 1
    input_id: str
    input_hash: str = ""
    case_id: Optional[str] = None
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
    evidence_ids: list[str] = Field(default_factory=list)
    source_lines: list[int] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.input_hash and self.input_values:
            canonical = json.dumps(self.input_values, sort_keys=True, separators=(",", ":"))
            object.__setattr__(self, "input_hash", hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16])


class ComparisonRecord(BaseModel):
    """Audit record capturing side-by-side comparison of legacy and modern executions."""
    comparison_id: str
    oracle_id: str
    oracle_version: int = 1
    oracle_set_hash: str = ""
    input_id: str
    input_hash: str = ""
    input_values: dict[str, Any]
    legacy_observation: Observation
    modern_observation: Observation
    legacy_eval_report: OracleEvaluationReport
    modern_eval_report: OracleEvaluationReport
    equivalence_outcome: Literal[
        "MATCH",
        "MATCH_PASS",
        "MODERN_REGRESSION",
        "REFERENCE_INCONSISTENT",
        "MUTUAL_VIOLATION",
        "NOT_APPLICABLE",
        "INVALID_INPUT",
        "EXECUTION_ERROR",
    ]
    timestamp: str = ""


class ImmutabilityError(ValueError):
    """Raised when an attempt is made to overwrite or tamper with an immutable certification record."""
    pass


class CertificationInputSet(BaseModel):
    """Immutable record of the exact input dataset used for a certification run."""
    model_config = {"frozen": True, "protected_namespaces": ()}

    input_set_id: str
    version: int = 1
    generator_type: str = "deterministic_phase11"
    generator_config: dict[str, Any] = Field(default_factory=dict)
    seed: int = 42
    input_count: int = 0
    canonical_hash: str = ""
    created_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class CertificationCase(BaseModel):
    """A single execution observation mapped to its legacy and modern output."""
    model_config = {"frozen": True, "protected_namespaces": ()}

    case_id: str
    run_id: str
    input_set_id: str
    case_index: int
    input_id: str = ""
    input_json: str
    input_hash: str
    legacy_output_json: str
    modern_output_json: str
    execution_time_ms: float = 0.0
    oracle_result: str
    classification: str
    severity: str = "medium"
    violated_oracle_ids: list[str] = Field(default_factory=list)


class CertificationContext(BaseModel):
    """Authoritative execution context for a single benchmark certification run.
    Serves as the single source of truth for the UI, API, and audit trail.
    """
    model_config = {"protected_namespaces": ()}

    benchmark_id: str = "default_project"
    benchmark_version: str = "1.0.0"
    benchmark_name: str = "Default Project"
    benchmark_provenance: str = "CONTROLLED"  # "CONTROLLED", "REALISTIC", "PUBLIC", "AUTHENTIC_PUBLIC_MIGRATION"
    dataset_id: str = "default"
    dataset_version: str = "1.0.0"
    dataset_checksum: str = ""
    evaluation_mode: str = "CONTROLLED"  # "CONTROLLED" or "FULL_BEACON"
    modernization_variant_id: str = "clean_v2"
    modernization_variant_name: str = "Clean Modernization"
    modernization_provenance: str = "INDEPENDENT_REIMPLEMENTATION"  # "INDEPENDENT_REIMPLEMENTATION", "CONTROLLED_MUTATION"
    legacy_implementation_id: str = ""
    legacy_implementation_hash: str = ""
    modernized_implementation_id: str = ""
    modernized_implementation_hash: str = ""
    oracle_set_id: str = ""
    oracle_set_hash: str = ""
    oracle_source_type: str = "CONTROLLED_ORACLE_SET"  # "CONTROLLED_ORACLE_SET", "FULL_BEACON_DISCOVERED", "FULL_BEACON_OFFLINE_FALLBACK"
    policy_id: str = "POL-DEFAULT"
    policy_hash: str = ""
    input_set_id: str = ""
    input_set_hash: str = ""
    certification_run_id: str = ""
    certification_artifact_id: str = ""
    certification_artifact_hash: str = ""
    run_timestamp: str = ""
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    run_status: str = "NOT_CERTIFIED"


def compute_input_set_canonical_hash(
    items: list[Union[CertificationCase, CertificationTestInput, dict[str, Any]]]
) -> str:
    """Computes deterministic SHA-256 canonical hash across the complete ordered input dataset.
    Reconstructed from either CertificationCase records or CertificationTestInput items,
    including every input's stable ID and canonical input values with deterministic ordering
    and stable JSON serialization.
    """
    canonical_entries = []
    for idx, item in enumerate(items):
        if isinstance(item, CertificationCase):
            raw_inp = item.input_json
            inp_vals = json.loads(raw_inp) if isinstance(raw_inp, str) else raw_inp
            canonical_entries.append({
                "case_index": item.case_index,
                "input_id": item.input_id or item.input_hash,
                "input_values": inp_vals,
            })
        elif isinstance(item, CertificationTestInput):
            canonical_entries.append({
                "case_index": idx,
                "input_id": item.input_id or item.input_hash,
                "input_values": item.values,
            })
        elif isinstance(item, dict):
            c_idx = item.get("case_index", item.get("index", idx))
            inp_id = item.get("input_hash", item.get("input_id", f"INP-{c_idx}"))
            raw_inp = item.get("input_values", item.get("input_json", item.get("values", {})))
            inp_vals = json.loads(raw_inp) if isinstance(raw_inp, str) else raw_inp
            canonical_entries.append({
                "case_index": c_idx,
                "input_id": inp_id,
                "input_values": inp_vals,
            })
    canonical_entries.sort(key=lambda x: x["case_index"])
    canonical_json = json.dumps(canonical_entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_input_set_integrity(input_set: CertificationInputSet, cases: list[CertificationCase]) -> bool:
    """Verifies that the reconstructed hash from persisted cases matches the stored input-set canonical hash,
    and that case counts and references match."""
    if not input_set or not cases:
        return False
    if len(cases) != input_set.input_count:
        return False
    for c in cases:
        if c.input_set_id != input_set.input_set_id:
            return False
    reconstructed = compute_input_set_canonical_hash(cases)
    return reconstructed == input_set.canonical_hash



class OracleEquivalenceMetrics(BaseModel):
    """Probe-level behavioral metrics for a single oracle."""
    oracle_id: str
    total_probes: int = 0
    applicable_probes: int = 0
    matching_probes: int = 0
    legacy_passes: int = 0
    modern_passes: int = 0
    modern_regressions: int = 0
    reference_inconsistencies: int = 0
    mutual_violations: int = 0
    invalid_inputs: int = 0
    execution_errors: int = 0
    not_applicable: int = 0
    oracle_equivalence_rate: float = 1.0


class CertificationPolicy(BaseModel):
    """Versioned and deterministic policy governing certification rules & thresholds."""
    policy_id: str = "POL-DEFAULT"
    version: int = 1
    name: str = "Standard Behavioral Certification Policy"
    min_equivalence_score: float = 0.80
    min_oracle_coverage: float = 1.0  # 100% of oracles in frozen set must be exercised
    min_applicable_probes_per_oracle: int = 5
    allow_warnings: bool = False  # If True, non-critical regressions may yield CERTIFIED_WITH_WARNINGS
    max_permitted_execution_errors: int = 0
    max_permitted_invalid_inputs: int = 0
    block_on_critical_regression: bool = True
    block_on_reference_inconsistent: bool = True
    block_on_mutual_violation: bool = True
    policy_hash: str = ""
    statement: str = (
        "Certification is relative to the frozen validated oracle set and tested input domain. "
        "It is not a mathematical proof of arbitrary program equivalence."
    )

    def compute_hash(self) -> str:
        """Computes deterministic SHA-256 hash of policy rules."""
        data = {
            "policy_id": self.policy_id,
            "version": self.version,
            "min_equivalence_score": self.min_equivalence_score,
            "min_oracle_coverage": self.min_oracle_coverage,
            "min_applicable_probes_per_oracle": self.min_applicable_probes_per_oracle,
            "allow_warnings": self.allow_warnings,
            "max_permitted_execution_errors": self.max_permitted_execution_errors,
            "max_permitted_invalid_inputs": self.max_permitted_invalid_inputs,
            "block_on_critical_regression": self.block_on_critical_regression,
            "block_on_reference_inconsistent": self.block_on_reference_inconsistent,
            "block_on_mutual_violation": self.block_on_mutual_violation,
        }
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PerOracleCertificationSummary(BaseModel):
    """Detailed summary and status of a single oracle within a certification run."""
    oracle_id: str
    oracle_version: int = 1
    oracle_hash: str = ""
    severity: str = "medium"
    confidence: float = 1.0
    domain: str = "business_logic"
    condition_str: str = ""
    consequence_str: str = ""
    total_probes: int = 0
    applicable_probes: int = 0
    matching_probes: int = 0
    legacy_passes: int = 0
    modern_passes: int = 0
    modern_regressions: int = 0
    reference_inconsistencies: int = 0
    mutual_violations: int = 0
    invalid_inputs: int = 0
    execution_errors: int = 0
    not_applicable: int = 0
    oracle_equivalence_rate: float = 1.0
    oracle_status: Literal[
        "PASS",
        "REGRESSION",
        "REFERENCE_INCONSISTENT",
        "MUTUAL_VIOLATION",
        "INSUFFICIENT_COVERAGE",
        "ERROR",
    ] = "PASS"
    counterexamples: list[BehavioralRegression] = Field(default_factory=list)


class CertificationMetrics(BaseModel):
    """Aggregated quantitative metrics for the entire certification run."""
    total_inputs: int = 0
    applicable_inputs: int = 0
    not_applicable: int = 0
    matching_probes: int = 0
    modern_regressions: int = 0
    reference_inconsistencies: int = 0
    mutual_violations: int = 0
    invalid_inputs: int = 0
    execution_errors: int = 0
    critical_failures: int = 0
    non_critical_failures: int = 0
    oracle_count: int = 0
    oracles_exercised: int = 0
    oracle_coverage_pct: float = 0.0
    overall_equivalence_score: float = 0.0


class CertificationArtifact(BaseModel):
    """Immutable, content-addressable certification certificate produced by BEACON."""
    model_config = {"frozen": True, "protected_namespaces": ()}

    certification_id: str
    project_id: str = "default_project"
    benchmark_id: Optional[str] = None
    evaluation_mode: Optional[str] = "CONTROLLED"
    modernization_variant: Optional[str] = "clean_v2"
    dataset_checksum: Optional[str] = ""
    oracle_source_type: Optional[str] = "CONTROLLED_ORACLE_SET"
    context: Optional[CertificationContext] = None
    legacy_version: str = "1.0.0"
    modernized_version: str = "2.0.0"
    oracle_set_id: str = ""
    oracle_set_version: int = 1
    oracle_set_hash: str = ""
    input_set_id: str = ""
    input_set_hash: str = ""
    certification_policy_id: str = "POL-DEFAULT"
    certification_policy_version: int = 1
    certification_policy_hash: str = ""
    certification_engine_version: str = "1.0.0"
    timestamp: str = ""
    reproducibility_state: Literal["FULLY_REPRODUCIBLE", "LEGACY_PARTIAL"] = "FULLY_REPRODUCIBLE"
    status: CertificationStatus = CertificationStatus.NOT_CERTIFIED
    certified: bool = False
    score: float = 0.0
    metrics: CertificationMetrics
    domain_scores: dict[str, float] = Field(default_factory=dict)
    oracle_summaries: list[PerOracleCertificationSummary] = Field(default_factory=list)
    regressions: list[BehavioralRegression] = Field(default_factory=list)
    reference_inconsistencies: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    content_hash: str = ""  # SHA-256 over canonical certificate JSON
    statement: str = (
        "This certificate represents quantified behavioral equivalence relative to the frozen validated oracle set "
        "and tested input domain under the declared certification policy. It does not constitute a formal mathematical proof of arbitrary program equivalence."
    )


def compute_artifact_content_hash(artifact: Union[CertificationArtifact, dict[str, Any]]) -> str:
    """Computes deterministic SHA-256 content hash across all material fields of a CertificationArtifact,
    excluding only the content_hash field itself and context.certification_artifact_hash to avoid circular hashing.
    """
    if isinstance(artifact, CertificationArtifact):
        data = artifact.model_dump(mode="json")
    else:
        data = dict(artifact)

    data.pop("content_hash", None)
    if isinstance(data.get("context"), dict):
        data["context"].pop("certification_artifact_hash", None)

    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_artifact_integrity(artifact: CertificationArtifact) -> bool:
    """Verifies that the stored content_hash matches the SHA-256 digest of its canonical content."""
    if not artifact.content_hash:
        return False
    computed = compute_artifact_content_hash(artifact)
    return computed == artifact.content_hash


class CrossVersionCertificationReport(BaseModel):
    """Backward-compatible Phase 9 / 10 cross-version report representation."""
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
    total_matching_probes: int = 0
    total_regressions: int = 0
    total_reference_inconsistencies: int = 0
    total_mutual_violations: int = 0
    total_invalid_inputs: int = 0
    total_execution_errors: int = 0
    total_not_applicable: int = 0
    certified: bool = False
    statement: str = (
        "This report measures behavioral equivalence relative to the frozen validated oracle set "
        "and tested input domain. It does not constitute a formal mathematical proof of arbitrary program equivalence."
    )
