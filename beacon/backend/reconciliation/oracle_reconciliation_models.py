"""BEACON V2 — Phase 7/8 Authoritative Oracle Reconciliation Domain Models.

Defines data models, binding structures, coverage metrics, and integrity records
for end-to-end reconciliation between frozen OracleSets, accepted InputSets,
execution observations, source identities, and certification artifacts.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class OracleReconciliationStatus(str, Enum):
    """Authoritative lifecycle reconciliation state between OracleSet, InputSet, and execution observations."""
    PENDING = "PENDING"
    """Reconciliation has been initialized or is awaiting execution evidence."""

    RECONCILED = "RECONCILED"
    """All mandatory integrity, identity, and binding checks passed; all required oracles are bound to valid inputs and execution observations."""

    PARTIALLY_RECONCILED = "PARTIALLY_RECONCILED"
    """Integrity checks passed and some required oracles are bound, but coverage is below 100% (some required oracles lack valid execution bindings)."""

    CONFLICT = "CONFLICT"
    """Unresolved contradictory rules or contradictory execution evidence bindings detected across the run."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    """Mandatory evidence artifacts (OracleSet, accepted InputSet, or execution cases) are missing or inaccessible for this run."""

    FAILED = "FAILED"
    """Cryptographic hash mismatch, tampering, application ID mismatch, or integrity verification violation detected."""


class OracleBindingStatus(str, Enum):
    """Binding status of an individual oracle rule to inputs and execution observations."""
    BOUND = "BOUND"
    PARTIALLY_BOUND = "PARTIALLY_BOUND"
    UNBOUND = "UNBOUND"
    CONFLICT = "CONFLICT"
    EXCLUDED = "EXCLUDED"


class OracleBinding(BaseModel):
    """Detailed binding record connecting an oracle rule to accepted inputs and verified execution evidence."""
    model_config = ConfigDict(extra="ignore")

    oracle_id: str
    oracle_version: int = 1
    rule_description: str = ""
    rule_source: str = ""
    is_required: bool = True
    bound_input_ids: list[str] = Field(default_factory=list)
    legacy_observations_count: int = 0
    modern_observations_count: int = 0
    matching_observations_count: int = 0
    divergent_observations_count: int = 0
    failed_observations_count: int = 0
    binding_status: OracleBindingStatus = OracleBindingStatus.UNBOUND
    notes: list[str] = Field(default_factory=list)


class OracleBindingCounts(BaseModel):
    """Quantitative summary of oracle bindings across the certification run."""
    model_config = ConfigDict(extra="ignore")

    total_required_bindings: int = 0
    matched_bindings: int = 0
    missing_bindings: int = 0
    unmatched_observations: int = 0
    conflicting_bindings: int = 0
    optional_bindings: int = 0
    excluded_bindings: int = 0


def compute_reconciliation_evidence_hash(data: dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 digest over the canonical reconciliation record data."""
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class OracleReconciliationRecord(BaseModel):
    """Authoritative, persisted record capturing the full outcome of Oracle Reconciliation for a certification run."""
    model_config = ConfigDict(extra="ignore")

    reconciliation_id: str
    run_id: str
    certification_id: str = ""
    application_id: str = ""
    oracle_set_id: str = ""
    oracle_set_hash: str = ""
    input_set_id: str = ""
    input_set_hash: str = ""
    legacy_source_hash: str = ""
    modern_source_hash: str = ""
    status: OracleReconciliationStatus = OracleReconciliationStatus.NOT_AVAILABLE
    status_reason: str = ""
    coverage: Optional[float] = None
    binding_counts: OracleBindingCounts = Field(default_factory=OracleBindingCounts)
    bindings: list[OracleBinding] = Field(default_factory=list)
    excluded_reasons: list[str] = Field(default_factory=list)
    policy_version: str = "1.0.0"
    evidence_hashes: dict[str, str] = Field(default_factory=dict)
    evidence_hash: str = ""
    reproducibility_state: Literal["FULLY_REPRODUCIBLE", "LEGACY_PARTIAL"] = "FULLY_REPRODUCIBLE"
    failure_reasons: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_evidence_hash(self) -> str:
        """Computes deterministic digest across all verified identity hashes, status, and binding counts."""
        payload = {
            "reconciliation_id": self.reconciliation_id,
            "run_id": self.run_id,
            "certification_id": self.certification_id,
            "application_id": self.application_id,
            "oracle_set_id": self.oracle_set_id,
            "oracle_set_hash": self.oracle_set_hash,
            "input_set_id": self.input_set_id,
            "input_set_hash": self.input_set_hash,
            "legacy_source_hash": self.legacy_source_hash,
            "modern_source_hash": self.modern_source_hash,
            "status": self.status.value,
            "coverage": round(self.coverage, 6) if self.coverage is not None else None,
            "binding_counts": self.binding_counts.model_dump(),
            "policy_version": self.policy_version,
            "failure_reasons": sorted(self.failure_reasons),
            "evidence_hashes": {k: self.evidence_hashes[k] for k in sorted(self.evidence_hashes)},
        }
        return compute_reconciliation_evidence_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.evidence_hash:
            object.__setattr__(self, "evidence_hash", self.compute_evidence_hash())
