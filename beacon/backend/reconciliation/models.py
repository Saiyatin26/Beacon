"""BEACON V2 — Phase 7 Rule Reconciliation & OracleSet Domain Models.

Defines the core data models for reconciled behavioral rules, conflict records,
decision audit traces, deterministic reconciliation policies, and versioned OracleSets.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class OracleSetStatus(str, Enum):
    """Lifecycle and readiness status of an OracleSet for certification consumption."""
    DRAFT = "DRAFT"            # Incomplete or under review; not ready for certification
    READY = "READY"            # Fully reconciled with zero unresolved conflicts; ready for certification
    BLOCKED = "BLOCKED"        # Material unresolved conflicts prevent certification readiness
    SUPERSEDED = "SUPERSEDED"  # Replaced by a newer versioned OracleSet


class RuleRelationship(str, Enum):
    """Pairwise semantic relationship classification between two behavioral rules."""
    EQUIVALENT = "EQUIVALENT"                    # Exact or semantically identical conditions and outcomes
    DUPLICATE = "DUPLICATE"                      # Redundant rule with identical behavior
    COMPATIBLE = "COMPATIBLE"                    # Non-conflicting rules applying to distinct or nested contexts
    SPECIALIZATION = "SPECIALIZATION"            # Rule A is a narrower sub-case of Rule B with compatible behavior
    GENERALIZATION = "GENERALIZATION"            # Rule A is a broader super-case of Rule B with compatible behavior
    CONFLICT = "CONFLICT"                        # Incompatible outcomes for overlapping or identical conditions
    INDEPENDENT = "INDEPENDENT"                  # Disjoint rule scopes with zero semantic interaction
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"  # Cannot determine relationship with available data


class ResolutionState(str, Enum):
    """Resolution lifecycle state of a candidate or rule within Phase 7."""
    PROPOSED = "PROPOSED"          # Raw rule / candidate ingested
    NORMALIZED = "NORMALIZED"      # Normalized to canonical representation
    SUPPORTED = "SUPPORTED"        # Backed by valid evidence or user specification
    CONFLICTED = "CONFLICTED"      # Involved in an unresolved behavioral contradiction
    RESOLVED = "RESOLVED"          # Conflict resolved via explicit policy or human override
    APPROVED = "APPROVED"          # Admitted into the final certification OracleSet
    REJECTED = "REJECTED"          # Excluded due to ineligibility, contradiction, or insufficient evidence
    INCONCLUSIVE = "INCONCLUSIVE"  # Evidence or definition insufficient for admission


class RuleProvenanceSource(str, Enum):
    """Origin provenance category of an approved or reconciled rule."""
    USER_DEFINED = "USER_DEFINED"  # Originated from Phase 5 intentional business rules
    DISCOVERED = "DISCOVERED"      # Originated from Phase 6 empirical discovery
    MERGED = "MERGED"              # Fused from multiple user and/or discovered sources


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


class DecisionTraceRecord(BaseModel):
    """Step-by-step auditable record explaining a specific reconciliation decision."""
    model_config = ConfigDict(extra="ignore")

    trace_id: str = ""
    source_id: str
    source_type: Literal["USER_DEFINED", "DISCOVERED"]
    normalized_expression: str
    decision: Literal["ADMITTED", "MERGED", "REJECTED", "CONFLICTED", "BLOCKED"]
    reason: str
    target_oracle_rule_id: Optional[str] = None
    related_rule_ids: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RuleConflict(BaseModel):
    """Auditable record of a behavioral contradiction between rules."""
    model_config = ConfigDict(extra="ignore")

    conflict_id: str
    rule_a_id: str
    rule_b_id: str
    rule_a_source: str
    rule_b_source: str
    relationship: RuleRelationship = RuleRelationship.CONFLICT
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    resolution_status: Literal["UNRESOLVED", "RESOLVED_USER_OVERRIDE", "RESOLVED_MANUAL", "SUPPRESSED"] = "UNRESOLVED"
    resolution_metadata: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_fingerprint(self) -> str:
        """Computes a deterministic hash over canonical conflict participants and reason."""
        sorted_pair = sorted([
            f"{self.rule_a_id}:{self.rule_a_source}",
            f"{self.rule_b_id}:{self.rule_b_source}",
        ])
        payload = {
            "participants": sorted_pair,
            "relationship": self.relationship.value,
            "reason": self.reason.strip(),
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", self.compute_fingerprint())


class OracleRule(BaseModel):
    """Canonical behavioral rule admitted into a certification-ready OracleSet."""
    model_config = ConfigDict(extra="ignore")

    rule_id: str
    rule_type: str
    name: str = ""
    description: str = ""
    canonical_expression: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    expected_behavior: dict[str, Any] = Field(default_factory=dict)
    role_scope: str = "reference"  # "reference", "target", "both"
    source: RuleProvenanceSource = RuleProvenanceSource.USER_DEFINED
    resolution_state: ResolutionState = ResolutionState.APPROVED

    # Empirical Metrics & Evidence Provenance
    confidence: float = 1.0
    support_count: int = 0
    contradiction_count: int = 0
    unknown_count: int = 0
    applicable_count: int = 0

    # Backing IDs
    evidence_ids: list[str] = Field(default_factory=list)
    input_ids: list[str] = Field(default_factory=list)
    source_rule_ids: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    candidate_fingerprints: list[str] = Field(default_factory=list)

    # Auditing
    decision_trace: list[DecisionTraceRecord] = Field(default_factory=list)
    fingerprint: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over semantic rule fields."""
        payload = {
            "rule_type": self.rule_type,
            "canonical_expression": self.canonical_expression.strip(),
            "conditions": self.conditions,
            "expected_behavior": self.expected_behavior,
            "role_scope": self.role_scope,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", self.compute_fingerprint())


# Backward-compatible alias
ReconciledRule = OracleRule


class ReconciliationPolicy(BaseModel):
    """Configuration governing Phase 7 candidate eligibility, deduplication, and approval.
    
    Fail-Closed Guarantees:
    - Unresolved material conflicts ALWAYS result in OracleSetStatus.BLOCKED.
    - No silent automatic overrides are permitted between conflicting rules.
    """
    model_config = ConfigDict(extra="ignore")

    require_validated_candidates: bool = True  # Only admit Phase 6 VALIDATED candidates
    minimum_support_count: int = 2
    minimum_confidence: float = 0.8
    # Deprecated fields retained for schema compatibility; fail-closed behavior is always enforced
    allow_unresolved_conflicts_in_ready: bool = False  # Deprecated: engine always marks unresolved conflicts as BLOCKED
    prefer_user_rules_on_conflict: bool = False        # Deprecated: engine always preserves both rules and flags conflict
    auto_merge_equivalent_rules: bool = True           # Deprecated: semantic merging of equivalent rules is mandatory
    policy_version: str = "1.0.0"

    def compute_policy_hash(self) -> str:
        """Computes a deterministic SHA-256 fingerprint of the effective policy configuration."""
        d = {
            "require_validated_candidates": self.require_validated_candidates,
            "minimum_support_count": self.minimum_support_count,
            "minimum_confidence": self.minimum_confidence,
            "policy_version": self.policy_version,
        }
        return compute_deterministic_hash(d)


class OracleSet(BaseModel):
    """Frozen, auditable behavioral specification for certification runs."""
    model_config = ConfigDict(extra="ignore")

    oracle_set_id: str
    application_id: str
    version: int = 1
    status: OracleSetStatus = OracleSetStatus.READY
    rules: list[OracleRule] = Field(default_factory=list)
    conflicts: list[RuleConflict] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    oracle_set_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)

    def compute_oracle_set_hash(self) -> str:
        """Computes deterministic SHA-256 digest across all canonical rule definitions, provenance, and conflict hashes."""
        ordered_rules = [
            {
                "rule_id": r.rule_id,
                "fingerprint": r.fingerprint,
                "rule_type": r.rule_type,
                "canonical_expression": r.canonical_expression,
                "conditions": r.conditions,
                "expected_behavior": r.expected_behavior,
                "role_scope": r.role_scope,
                "source": r.source.value,
                "confidence": r.confidence,
                "support_count": r.support_count,
                "contradiction_count": r.contradiction_count,
                "unknown_count": r.unknown_count,
                "applicable_count": r.applicable_count,
                "resolution_state": r.resolution_state.value,
                "evidence_ids": sorted(r.evidence_ids),
                "input_ids": sorted(r.input_ids),
                "source_rule_ids": sorted(r.source_rule_ids),
                "source_candidate_ids": sorted(r.source_candidate_ids),
                "candidate_fingerprints": sorted(r.candidate_fingerprints),
                "metadata": r.metadata,
            }
            for r in sorted(self.rules, key=lambda x: (x.fingerprint, x.role_scope, x.rule_id))
        ]
        ordered_conflicts = [
            {
                "conflict_id": c.conflict_id,
                "fingerprint": c.fingerprint,
                "rule_a_id": c.rule_a_id,
                "rule_b_id": c.rule_b_id,
                "rule_a_source": c.rule_a_source,
                "rule_b_source": c.rule_b_source,
                "relationship": c.relationship.value,
                "reason": c.reason,
                "evidence_ids": sorted(c.evidence_ids),
                "resolution_status": c.resolution_status,
                "resolution_metadata": c.resolution_metadata,
            }
            for c in sorted(self.conflicts, key=lambda x: x.fingerprint)
        ]
        payload = {
            "application_id": self.application_id,
            "version": self.version,
            "status": self.status.value,
            "rules": ordered_rules,
            "conflicts": ordered_conflicts,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.oracle_set_hash:
            object.__setattr__(self, "oracle_set_hash", self.compute_oracle_set_hash())


class ReconciliationDiagnostic(BaseModel):
    """Diagnostic entry logged during reconciliation steps."""
    model_config = ConfigDict(extra="ignore")

    stage: str
    severity: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReconciliationResult(BaseModel):
    """Top-level immutable container representing the outcome of a reconciliation session."""
    model_config = ConfigDict(extra="ignore")

    run_id: str
    application_id: str
    session_id: str = ""
    policy: ReconciliationPolicy = Field(default_factory=ReconciliationPolicy)
    policy_hash: str = ""

    # Counts
    input_rule_count: int = 0
    input_candidate_count: int = 0
    normalized_count: int = 0
    merged_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    conflict_count: int = 0
    unresolved_conflict_count: int = 0

    # Payloads
    rules: list[OracleRule] = Field(default_factory=list)
    conflicts: list[RuleConflict] = Field(default_factory=list)
    decision_traces: list[DecisionTraceRecord] = Field(default_factory=list)
    diagnostics: list[ReconciliationDiagnostic] = Field(default_factory=list)

    # OracleSet Artifact
    oracle_set: Optional[OracleSet] = None
    oracle_set_id: str = ""
    oracle_set_version: int = 1

    overall_status: str = "COMPLETE"  # "COMPLETE", "PARTIAL", "FAILED"
    persistence_status: str = "NOT_REQUESTED"  # "NOT_REQUESTED", "PERSISTED", "FAILED"
    result_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_result_hash(self) -> str:
        """Computes deterministic SHA-256 digest over the entire semantic reconciliation outcome."""
        ordered_rule_ids = [
            {"rule_id": r.rule_id, "fingerprint": r.fingerprint, "role_scope": r.role_scope}
            for r in sorted(self.rules, key=lambda x: (x.fingerprint, x.role_scope, x.rule_id))
        ]
        ordered_conflict_ids = [
            {"conflict_id": c.conflict_id, "fingerprint": c.fingerprint}
            for c in sorted(self.conflicts, key=lambda x: x.fingerprint)
        ]
        payload = {
            "application_id": self.application_id,
            "policy_hash": self.policy_hash,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "conflict_count": self.conflict_count,
            "unresolved_conflict_count": self.unresolved_conflict_count,
            "oracle_set_hash": self.oracle_set.oracle_set_hash if self.oracle_set else "",
            "overall_status": self.overall_status,
            "rules": ordered_rule_ids,
            "conflicts": ordered_conflict_ids,
        }
        return compute_deterministic_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.policy_hash:
            object.__setattr__(self, "policy_hash", self.policy.compute_policy_hash())
        if not self.result_hash:
            object.__setattr__(self, "result_hash", self.compute_result_hash())
