"""BEACON V2 — Phase 10 Intelligent Agent & Detailed Certification Explanations Domain Models.

Defines canonical data contracts for structured explanations, bounded explanation context,
rule impacts, evidence traces, missing evidence, uncertainty disclosures, investigation
recommendations, and interactive certification Q&A.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from evaluation.models import BehaviorDimension, EvaluationVerdict


class ExplanationVerdict(str, Enum):
    """Authoritative verdict states for explanations, aligned with BEACON certification statuses."""
    CERTIFIED = "CERTIFIED"
    CERTIFIED_WITH_WARNINGS = "CERTIFIED_WITH_WARNINGS"
    NOT_CERTIFIED = "NOT_CERTIFIED"
    REFERENCE_INCONSISTENT = "REFERENCE_INCONSISTENT"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    ORACLE_SET_INVALID = "ORACLE_SET_INVALID"
    EQUIVALENT = "EQUIVALENT"
    DIFFERENT = "DIFFERENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


class EvidenceSupportLevel(str, Enum):
    """Epistemic certainty level supporting a specific explanation claim."""
    DETERMINISTIC_FACT = "DETERMINISTIC_FACT"        # Directly verified by empirical Phase 3/4/8 ground truth evidence
    DETERMINISTIC_EVIDENCE = "DETERMINISTIC_FACT"    # Alias for DETERMINISTIC_FACT
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"              # Explicitly cited from verified Phase 9 company documentation
    DERIVED = "DERIVED"                              # Deterministically computed from authoritative data
    INFERENCE = "INFERENCE"                          # Plausible hypothesis or deduction from verified rules/outputs
    INFERRED = "INFERENCE"                           # Alias for INFERENCE
    UNCERTAIN = "INFERENCE"                          # Alias for INFERENCE
    UNKNOWN = "UNKNOWN"                              # Completely unverifiable from available data


class GroundingClaimType(str, Enum):
    """Taxonomy of factual claims made by LLM or explanation layers for verification."""
    NUMERIC_VALUE = "NUMERIC_VALUE"
    DIMENSION_STATUS = "DIMENSION_STATUS"
    EVIDENCE_REFERENCE = "EVIDENCE_REFERENCE"
    RULE_REFERENCE = "RULE_REFERENCE"
    INPUT_REFERENCE = "INPUT_REFERENCE"
    VERDICT_CLAIM = "VERDICT_CLAIM"


class GroundingClaim(BaseModel):
    """Structured, verifiable claim produced during explanation or Q&A."""
    model_config = ConfigDict(extra="ignore")

    claim_type: GroundingClaimType = GroundingClaimType.NUMERIC_VALUE
    statement: str = ""
    field: Optional[str] = None
    role: Optional[str] = None  # REFERENCE, TARGET
    value: Optional[Any] = None
    input_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    rule_id: Optional[str] = None
    dimension: Optional[str] = None
    status: Optional[str] = None
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.DETERMINISTIC_FACT


class AuthoritativeFact(BaseModel):
    """Internal Phase 10 authoritative projection of empirical truth from Phases 3–8."""
    model_config = ConfigDict(extra="ignore")

    fact_type: str
    dimension: Optional[BehaviorDimension] = None
    input_id: Optional[str] = None
    input_hash: Optional[str] = None
    role: Optional[str] = None
    reference_value: Optional[Any] = None
    target_value: Optional[Any] = None
    difference_value: Optional[Any] = None
    evidence_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    source_phase: str = "PHASE_4"
    provenance: dict[str, Any] = Field(default_factory=dict)


class StateEvidenceFact(BaseModel):
    """Authoritative projection of empirical physical state observations (DATABASE, FILESYSTEM)."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    role: Optional[str] = None
    evidence_type: str = "STATE"
    resource: Optional[str] = None
    before: Optional[Any] = None
    after: Optional[Any] = None
    delta: Optional[Any] = None
    delta_detected: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[str] = None


class WorkflowTraceFact(BaseModel):
    """Authoritative projection of empirical execution trace timeline and event sequences."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    role: Optional[str] = None
    event_type: str = "INVOCATION"
    sequence: int = 0
    ordering: Optional[int] = None
    action: Optional[str] = None
    observed_divergence: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[str] = None


class ExplanationFinding(BaseModel):
    """A single structured observation or finding within a dimension."""
    model_config = ConfigDict(extra="ignore")

    finding_id: str = ""
    dimension: Optional[BehaviorDimension] = None
    statement: str
    support: EvidenceSupportLevel = EvidenceSupportLevel.DETERMINISTIC_FACT
    evidence_ids: list[str] = Field(default_factory=list)
    input_id: Optional[str] = None
    reference_value: Optional[Any] = None
    target_value: Optional[Any] = None
    difference_details: dict[str, Any] = Field(default_factory=dict)


class DimensionExplanation(BaseModel):
    """Detailed explanation for a single behavioral dimension."""
    model_config = ConfigDict(extra="ignore")

    dimension: BehaviorDimension
    status: str = "UNKNOWN"  # PASS, DIFFERENT, INCONCLUSIVE, NOT_APPLICABLE, ERROR, UNKNOWN
    reference_summary: str = ""
    target_summary: str = ""
    difference_summary: str = ""
    tolerance_applied: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    findings: list[ExplanationFinding] = Field(default_factory=list)


class RuleImpact(BaseModel):
    """Connects Phase 7 OracleSet rules or Phase 5/6 rules to observed behavior."""
    model_config = ConfigDict(extra="ignore")

    rule_id: str
    rule_description: str
    status: Literal["POTENTIALLY_AFFECTED", "VIOLATED", "COMPLIANT", "UNTESTED"] = "POTENTIALLY_AFFECTED"
    observed_behavior: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    relationship_to_verdict: str = ""
    limitation: str = "Evidence demonstrates behavioral deviation but does not establish underlying source code root cause."


class EvidenceTrace(BaseModel):
    """Audit-ready traceability record tying an explanation claim to underlying evidence."""
    model_config = ConfigDict(extra="ignore")

    claim_id: str
    claim_text: str
    evidence_id: Optional[str] = None
    input_id: str
    dimension: Optional[BehaviorDimension] = None
    role: Optional[str] = None  # reference, target, or paired
    source_type: str = "runtime_execution"
    evidence_hash: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class AffectedInput(BaseModel):
    """Details of a specific input that exposed behavioral difference or regression."""
    model_config = ConfigDict(extra="ignore")

    input_id: str
    input_hash: str = ""
    input_values: dict[str, Any] = Field(default_factory=dict)
    legacy_output: Optional[Any] = None
    modern_output: Optional[Any] = None
    violated_rules: list[str] = Field(default_factory=list)
    severity: str = "medium"


class MissingEvidence(BaseModel):
    """Explicit disclosure of absent evidence preventing conclusive evaluation."""
    model_config = ConfigDict(extra="ignore")

    dimension: BehaviorDimension
    description: str
    implication: str
    status: Literal["UNKNOWN", "INCONCLUSIVE"] = "INCONCLUSIVE"


class UncertaintyNote(BaseModel):
    """Explicit disclosure distinguishing proven facts from hypotheses."""
    model_config = ConfigDict(extra="ignore")

    topic: str
    claim: str
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.INFERENCE
    reason: str


class InvestigationRecommendation(BaseModel):
    """Actionable, evidence-driven investigation guidance for software engineers."""
    model_config = ConfigDict(extra="ignore")

    priority: int = 1  # 1 (Highest) to 5
    title: str
    description: str
    rationale: str
    evidence_references: list[str] = Field(default_factory=list)


class RetrievedKnowledgeCitation(BaseModel):
    """Citation of retrieved Phase 9 enterprise documentation."""
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    document_id: str
    filename: str
    content_snippet: str
    relevance_score: float = 0.0
    page_number: Optional[int] = None
    section_name: Optional[str] = None


class CompanyKnowledgeContext(BaseModel):
    """Encapsulates retrieved company knowledge context from Phase 9."""
    model_config = ConfigDict(extra="ignore")

    retrieval_query: str
    retrieval_fingerprint: str = ""
    citations: list[RetrievedKnowledgeCitation] = Field(default_factory=list)
    citation_note: str = "Company documentation provides domain context but does not supersede empirical certification evidence."


class GenerationMetadata(BaseModel):
    """Audit metadata describing how an explanation was generated."""
    model_config = ConfigDict(extra="ignore")

    provider: str = "offline"
    model: str = "deterministic"
    generation_mode: Literal["DETERMINISTIC", "ASSISTED", "LLM"] = "DETERMINISTIC"
    prompt_version: str = "v1.0"
    schema_version: str = "1.0.0"
    latency_ms: Optional[float] = None
    tokens_used: Optional[int] = None
    fallback_occurred: bool = False
    fallback_reason: Optional[str] = None
    reproducibility: Literal["DETERMINISTIC_CANONICAL", "NOT_GUARANTEED"] = "DETERMINISTIC_CANONICAL"


class ExplanationContext(BaseModel):
    """Bounded, redacted structured context prepared for explanation synthesis."""
    model_config = ConfigDict(extra="ignore")

    certification_id: str
    application_id: str = ""
    project_id: str = ""
    session_id: Optional[str] = None
    authoritative_verdict: str = "NOT_CERTIFIED"
    equivalence_score: Optional[float] = None
    unique_inputs_count: Optional[int] = None
    matching_cases_count: Optional[int] = None
    regression_cases_count: Optional[int] = None
    dimensions_evaluated: list[BehaviorDimension] = Field(default_factory=list)
    differences_summary: list[dict[str, Any]] = Field(default_factory=list)
    valid_evidence_ids: list[str] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    valid_rule_ids: list[str] = Field(default_factory=list)
    valid_input_ids: list[str] = Field(default_factory=list)
    rules_context: list[dict[str, Any]] = Field(default_factory=list)
    thresholds_context: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    state_facts: list[StateEvidenceFact] = Field(default_factory=list)
    workflow_facts: list[WorkflowTraceFact] = Field(default_factory=list)
    knowledge_context: Optional[CompanyKnowledgeContext] = None
    user_question: Optional[str] = None

    def compute_context_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over all canonical semantic context fields."""
        # Canonical representation of all material fields
        payload = {
            "certification_id": self.certification_id,
            "application_id": self.application_id,
            "project_id": self.project_id,
            "session_id": self.session_id or "",
            "authoritative_verdict": self.authoritative_verdict,
            "equivalence_score": round(self.equivalence_score, 6) if self.equivalence_score is not None else None,
            "unique_inputs_count": self.unique_inputs_count,
            "matching_cases_count": self.matching_cases_count,
            "regression_cases_count": self.regression_cases_count,
            "dimensions": sorted([d.value for d in self.dimensions_evaluated]),
            "differences_summary": sorted(
                self.differences_summary,
                key=lambda x: str(x.get("input_id", "")) + str(x.get("difference_id", ""))
            ),
            "valid_evidence_ids": sorted(self.valid_evidence_ids),
            "unresolved_evidence_ids": sorted(self.unresolved_evidence_ids),
            "valid_rule_ids": sorted(self.valid_rule_ids),
            "valid_input_ids": sorted(self.valid_input_ids),
            "rules_context": sorted(
                self.rules_context,
                key=lambda x: str(x.get("rule_id", ""))
            ),
            "thresholds_context": sorted(
                self.thresholds_context,
                key=lambda x: str(x.get("policy_id", "")) + str(x.get("metric", ""))
            ),
            "missing_evidence": sorted(
                [m.model_dump() for m in self.missing_evidence],
                key=lambda x: str(x.get("dimension", "")) + str(x.get("description", ""))
            ),
            "state_facts": sorted(
                [s.model_dump() for s in self.state_facts],
                key=lambda x: str(x.get("evidence_id", ""))
            ),
            "workflow_facts": sorted(
                [w.model_dump() for w in self.workflow_facts],
                key=lambda x: str(x.get("evidence_id", "")) + str(x.get("sequence", ""))
            ),
            "knowledge_retrieval_fingerprint": self.knowledge_context.retrieval_fingerprint if self.knowledge_context else "",
        }
        canonical_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda o: o.model_dump(mode="json") if hasattr(o, "model_dump") else (o.dict() if hasattr(o, "dict") else str(o)),
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def compute_cache_key(self, mode: str = "auto", use_company_knowledge: bool = True, prompt_version: str = "v1.0") -> str:
        """Computes comprehensive cache key accounting for context, configuration, and prompt version."""
        fp = self.compute_context_fingerprint()
        raw = f"{self.certification_id}:{fp}:{mode.lower()}:know={use_company_knowledge}:{prompt_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CertificationExplanation(BaseModel):
    """Canonical Phase 10 structured certification explanation."""
    model_config = ConfigDict(extra="ignore")

    explanation_id: str
    certification_id: str
    application_id: str = ""
    project_id: str = ""
    session_id: Optional[str] = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    explanation_version: str = "1.0.0"
    cache_key: str = ""
    persistence_status: str = "PERSISTED"  # PERSISTED, FAILED, NOT_PERSISTED
    audit_status: str = "PERSISTED"  # PERSISTED, FAILED, NOT_ATTEMPTED

    # Authoritative Ground Truth (Strictly derived from Phase 8 / Certification Artifact)
    overall_verdict: str
    is_authoritative_match: bool = False
    authoritative_match_status: str = "INCONCLUSIVE"  # CERTIFIED, NOT_CERTIFIED, INCONCLUSIVE, UNKNOWN

    # High-level Summaries
    executive_summary: str
    scope_summary: dict[str, Any] = Field(default_factory=dict)
    behavioral_summary: str

    # Structured Deep-Dives
    dimension_explanations: list[DimensionExplanation] = Field(default_factory=list)
    rule_impacts: list[RuleImpact] = Field(default_factory=list)
    evidence_traces: list[EvidenceTrace] = Field(default_factory=list)
    affected_inputs: list[AffectedInput] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    state_facts: list[StateEvidenceFact] = Field(default_factory=list)
    workflow_facts: list[WorkflowTraceFact] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    uncertainty_notes: list[UncertaintyNote] = Field(default_factory=list)
    company_knowledge_context: Optional[CompanyKnowledgeContext] = None
    investigation_recommendations: list[InvestigationRecommendation] = Field(default_factory=list)

    # Provenance & Fingerprint
    context_fingerprint: str = ""
    content_hash: str = ""
    generation_metadata: GenerationMetadata = Field(default_factory=GenerationMetadata)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA-256 hash over material explanation content."""
        data = self.model_dump(mode="json")
        data.pop("content_hash", None)
        data.pop("generated_at", None)
        data.pop("persistence_status", None)
        data.pop("audit_status", None)
        canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ExplanationRequest(BaseModel):
    """Payload to request or generate a certification explanation."""
    mode: Literal["auto", "deterministic", "assisted", "llm"] = "auto"
    use_company_knowledge: bool = True
    preferred_provider: Optional[str] = None
    custom_query: Optional[str] = None
    force_recompute: bool = False


class AskCertificationRequest(BaseModel):
    """Payload to ask an interactive question about a certification run."""
    question: str
    use_company_knowledge: bool = True
    preferred_provider: Optional[str] = None


class AskCertificationResponse(BaseModel):
    """Structured response to an interactive question about a certification run."""
    question: str
    answer: str
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.DETERMINISTIC_FACT
    referenced_evidence_ids: list[str] = Field(default_factory=list)
    referenced_rule_ids: list[str] = Field(default_factory=list)
    referenced_document_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    authoritative_verdict: str
    context_fingerprint: str
    generation_metadata: GenerationMetadata = Field(default_factory=GenerationMetadata)
    persistence_status: str = "PERSISTED"
    audit_status: str = "PERSISTED"

