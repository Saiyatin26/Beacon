"""Phase 15 — Unified Evidence Dossier and Explainability Models.

Defines the structured, immutable domain models for Evidence Dossiers,
traceability nodes, completeness reports, auditor annotations, and
deterministic explanations.
"""

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field


class EvidenceCompletenessReport(BaseModel):
    """Authoritative consistency and completeness audit report for a certification run."""
    model_config = {"protected_namespaces": ()}

    status: Literal["COMPLETE", "INCOMPLETE"] = "COMPLETE"
    completeness_score: float = 1.0
    missing_fields: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class SourceEvidence(BaseModel):
    """Audit evidence capturing dataset identity, provenance, schema, and checksum."""
    model_config = {"protected_namespaces": ()}

    dataset_id: str = ""
    dataset_name: str = ""
    version: Union[str, int] = "1.0.0"
    checksum: str = ""
    schema_fingerprint: str = ""
    inferred_schema: dict[str, str] = Field(default_factory=dict)
    row_count: int = 0
    declared_provenance: str = "CONTROLLED"
    source_reference: Optional[str] = None
    target_domain: Optional[str] = None
    is_custom_dataset: bool = False


class ImplementationEvidence(BaseModel):
    """Audit evidence capturing legacy and modern implementation identity and bytecode hashes."""
    model_config = {"protected_namespaces": ()}

    legacy_adapter_id: str = ""
    legacy_adapter_name: str = ""
    legacy_version: Union[str, int] = "1.0.0"
    legacy_implementation_hash: str = ""
    modernized_adapter_id: str = ""
    modernized_adapter_name: str = ""
    modernized_version: Union[str, int] = "2.0.0"
    modernized_implementation_hash: str = ""
    modernization_variant: str = "clean_v2"
    modernization_provenance: str = "INDEPENDENT_REIMPLEMENTATION"


class OracleEvidenceItem(BaseModel):
    """Detailed evidence item for a single behavioral oracle AST definition."""
    model_config = {"protected_namespaces": ()}

    oracle_id: str
    version: Union[str, int] = "1.0.0"
    severity: str = "HIGH"
    confidence: float = 1.0
    domain: str = "General"
    canonical_condition: str = ""
    consequence_variable: str = ""
    consequence_value: Any = None
    oracle_hash: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class OracleEvidence(BaseModel):
    """Audit evidence capturing frozen/discovered OracleSet metadata and AST rules."""
    model_config = {"protected_namespaces": ()}

    oracle_set_id: str = ""
    oracle_set_version: Union[str, int] = "1.0.0"
    oracle_set_hash: str = ""
    oracle_count: int = 0
    oracles: list[OracleEvidenceItem] = Field(default_factory=list)
    summaries: list[dict[str, Any]] = Field(default_factory=list)
    oracle_source_type: str = "CONTROLLED_ORACLE_SET"


class CounterexampleEvidenceItem(BaseModel):
    """Pinpointed regression counterexample with exact input, outputs, and rule violated."""
    model_config = {"protected_namespaces": ()}

    counterexample_id: str
    case_id: Optional[str] = None
    input_id: str = ""
    input_hash: str = ""
    oracle_id: str = ""
    severity: str = "HIGH"
    legacy_output: Any = None
    modern_output: Any = None
    difference_description: str = ""
    invariant_violated: str = ""
    sanitized_input_values: dict[str, Any] = Field(default_factory=dict)
    evidence_reference: str = ""


class ExecutionEvidence(BaseModel):
    """Disambiguated execution metrics, case counts, and equivalence score."""
    model_config = {"protected_namespaces": ()}

    total_inputs: int = 0
    total_cases: int = 0
    matching_cases: int = 0
    regression_cases: int = 0
    error_cases: int = 0
    counterexample_count: int = 0
    oracles_exercised: int = 0
    oracle_coverage_pct: float = 0.0
    equivalence_score: float = 0.0
    input_set_id: str = ""
    input_set_hash: str = ""
    execution_time_ms: float = 0.0


class PolicyEvidence(BaseModel):
    """Governing certification policy thresholds, rules, and satisfaction state."""
    model_config = {"protected_namespaces": ()}

    policy_id: str = "POL-DEFAULT"
    version: Union[str, int] = "1.0.0"
    policy_hash: str = ""
    min_equivalence_score: float = 0.80
    min_oracle_coverage: float = 0.0
    block_on_critical_regression: bool = True
    block_on_reference_inconsistent: bool = True
    block_on_mutual_violation: bool = True
    satisfied: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProvenanceEvidence(BaseModel):
    """Execution provenance, discovery mode, provider hierarchy, and LLM boundaries."""
    model_config = {"protected_namespaces": ()}

    evaluation_mode: str = "CONTROLLED"
    preferred_provider: str = "offline"
    actual_provider: str = "offline"
    model: str = "deterministic"
    fallback_occurred: bool = False
    fallback_chain: list[str] = Field(default_factory=list)
    fallback_reason: Optional[str] = None
    prompt_version: Optional[str] = None
    evidence_package_hash: Optional[str] = None
    allow_external_llm: bool = False


class CryptographicEvidence(BaseModel):
    """Complete 8-point cryptographic integrity hashes and verification status."""
    model_config = {"protected_namespaces": ()}

    artifact_hash: str = ""
    input_set_hash: str = ""
    dataset_checksum: str = ""
    legacy_implementation_hash: str = ""
    modernized_implementation_hash: str = ""
    oracle_set_hash: str = ""
    policy_hash: str = ""
    config_fingerprint: str = ""
    integrity_status: Literal["VERIFIED", "FAILED", "TAMPERED", "INCOMPLETE"] = "VERIFIED"
    verification_report: dict[str, Any] = Field(default_factory=dict)


class AuditorNote(BaseModel):
    """Human auditor review note stored in an isolated annotation layer."""
    model_config = {"protected_namespaces": ()}

    note_id: str
    certification_id: str
    project_id: str
    author: str = "Auditor"
    content: str
    timestamp: str


class EvidenceTraceNode(BaseModel):
    """Node in the directed evidence traceability graph / chain of custody."""
    model_config = {"protected_namespaces": ()}

    node_id: str
    node_type: str  # DATASET, INPUT_SET, IMPLEMENTATION_PAIR, ORACLE_SET, ORACLE_EVALUATION, COUNTEREXAMPLE_MATCH, POLICY, ARTIFACT, INTEGRITY_HASH
    label: str
    entity_id: Optional[str] = None
    status: str = "AVAILABLE"  # AVAILABLE, UNAVAILABLE, PASSED, FAILED, WARNING
    details: dict[str, Any] = Field(default_factory=dict)
    target_nodes: list[str] = Field(default_factory=list)


class StructuredExplanation(BaseModel):
    """Authoritative structured explanation of why a certification result was reached."""
    model_config = {"protected_namespaces": ()}

    dossier_id: str
    certification_id: str
    project_id: str
    authoritative_status: str
    headline: str
    what_was_certified: str
    dataset_used: str
    implementation_pair: str
    governing_oracles_and_policy: str
    evaluation_summary: str
    status_rationale: str  # Why Certified? / Why Not Certified? / Why Inconclusive?
    highest_severity_failures: list[dict[str, Any]] = Field(default_factory=list)
    evidence_references: list[dict[str, str]] = Field(default_factory=list)
    natural_language_explanation: str
    explanation_source: Literal["DETERMINISTIC_ENGINE", "LLM_ASSISTED_EXPLANATION"] = "DETERMINISTIC_ENGINE"
    explanation_provenance: dict[str, Any] = Field(default_factory=dict)


class EvidenceDossier(BaseModel):
    """Unified Evidence Dossier container for an entire certification run."""
    model_config = {"protected_namespaces": ()}

    dossier_id: str
    certification_id: str
    project_id: str
    created_at: str
    source_evidence: SourceEvidence = Field(default_factory=SourceEvidence)
    implementation_evidence: ImplementationEvidence = Field(default_factory=ImplementationEvidence)
    oracle_evidence: OracleEvidence = Field(default_factory=OracleEvidence)
    execution_evidence: ExecutionEvidence = Field(default_factory=ExecutionEvidence)
    counterexample_evidence: list[CounterexampleEvidenceItem] = Field(default_factory=list)
    policy_evidence: PolicyEvidence = Field(default_factory=PolicyEvidence)
    provenance_evidence: ProvenanceEvidence = Field(default_factory=ProvenanceEvidence)
    cryptographic_evidence: CryptographicEvidence = Field(default_factory=CryptographicEvidence)
    audit_timeline: list[dict[str, Any]] = Field(default_factory=list)
    completeness: EvidenceCompletenessReport = Field(default_factory=EvidenceCompletenessReport)
    notes: list[AuditorNote] = Field(default_factory=list)
    reused_from_run_id: Optional[str] = None
    is_reused_artifact: bool = False
    is_forced_recompute: bool = False
    dossier_hash: str = ""
