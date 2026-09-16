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
    DETERMINISTIC_EVIDENCE = "DETERMINISTIC_EVIDENCE"  # Directly verified by empirical Phase 3/4/8 evidence
    INFERRED = "INFERRED"                              # Logical deduction from verified rules and outputs
    UNCERTAIN = "UNCERTAIN"                            # Plausible hypothesis but not conclusively provable from evidence
    UNKNOWN = "UNKNOWN"                                # Completely unverifiable from available data


class ExplanationFinding(BaseModel):
    """A single structured observation or finding within a dimension."""
    model_config = ConfigDict(extra="ignore")

    finding_id: str = ""
    dimension: BehaviorDimension = BehaviorDimension.OUTPUT
    statement: str
    support: EvidenceSupportLevel = EvidenceSupportLevel.DETERMINISTIC_EVIDENCE
    evidence_ids: list[str] = Field(default_factory=list)
    reference_value: Optional[Any] = None
    target_value: Optional[Any] = None
    difference_details: dict[str, Any] = Field(default_factory=dict)


class DimensionExplanation(BaseModel):
    """Detailed explanation for a single behavioral dimension."""
    model_config = ConfigDict(extra="ignore")

    dimension: BehaviorDimension
    status: str = "PASS"  # PASS, DIFFERENT, INCONCLUSIVE, NOT_APPLICABLE, ERROR
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
    evidence_id: str
    input_id: str
    dimension: BehaviorDimension = BehaviorDimension.OUTPUT
    role: str = "target"  # reference, target, or paired
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
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.UNCERTAIN
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
    application_id: str = "default_app"
    project_id: str = "default_project"
    session_id: Optional[str] = None
    authoritative_verdict: str = "NOT_CERTIFIED"
    equivalence_score: float = 0.0
    unique_inputs_count: int = 0
    matching_cases_count: int = 0
    regression_cases_count: int = 0
    dimensions_evaluated: list[BehaviorDimension] = Field(default_factory=list)
    differences_summary: list[dict[str, Any]] = Field(default_factory=list)
    valid_evidence_ids: list[str] = Field(default_factory=list)
    valid_rule_ids: list[str] = Field(default_factory=list)
    valid_input_ids: list[str] = Field(default_factory=list)
    rules_context: list[dict[str, Any]] = Field(default_factory=list)
    thresholds_context: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    knowledge_context: Optional[CompanyKnowledgeContext] = None
    user_question: Optional[str] = None

    def compute_context_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over all canonical context fields."""
        payload = {
            "certification_id": self.certification_id,
            "application_id": self.application_id,
            "project_id": self.project_id,
            "authoritative_verdict": self.authoritative_verdict,
            "equivalence_score": round(self.equivalence_score, 4),
            "unique_inputs_count": self.unique_inputs_count,
            "matching_cases_count": self.matching_cases_count,
            "regression_cases_count": self.regression_cases_count,
            "dimensions": [d.value for d in sorted(self.dimensions_evaluated, key=lambda x: x.value)],
            "valid_evidence_ids": sorted(self.valid_evidence_ids),
            "valid_rule_ids": sorted(self.valid_rule_ids),
            "valid_input_ids": sorted(self.valid_input_ids),
            "knowledge_retrieval_fingerprint": self.knowledge_context.retrieval_fingerprint if self.knowledge_context else "",
        }
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class CertificationExplanation(BaseModel):
    """Canonical Phase 10 structured certification explanation."""
    model_config = ConfigDict(extra="ignore")

    explanation_id: str
    certification_id: str
    application_id: str = "default_app"
    project_id: str = "default_project"
    session_id: Optional[str] = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    explanation_version: str = "1.0.0"

    # Authoritative Ground Truth (Strictly derived from Phase 8 / Certification Artifact)
    overall_verdict: str
    is_authoritative_match: bool = True

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
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.DETERMINISTIC_EVIDENCE
    referenced_evidence_ids: list[str] = Field(default_factory=list)
    referenced_rule_ids: list[str] = Field(default_factory=list)
    referenced_document_ids: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    authoritative_verdict: str
    context_fingerprint: str
    generation_metadata: GenerationMetadata = Field(default_factory=GenerationMetadata)
