"""BEACON V2 — Phase 7 Rule Reconciliation & OracleSet Generation.

Provides deterministic reconciliation of Phase 5 user-defined business rules and Phase 6 discovered
candidate rules into certification-ready OracleSets with complete provenance, conflict tracking, and integrity hashes.
"""

from .engine import RuleReconciliationEngine, rule_reconciliation_engine
from .models import (
    DecisionTraceRecord,
    OracleRule,
    OracleSet,
    OracleSetStatus,
    ReconciliationDiagnostic,
    ReconciliationPolicy,
    ReconciliationResult,
    ResolutionState,
    RuleConflict,
    RuleProvenanceSource,
    RuleRelationship,
)
from .persistence import ReconciliationPersistenceStore, reconciliation_persistence

__all__ = [
    "RuleReconciliationEngine",
    "rule_reconciliation_engine",
    "ReconciliationPersistenceStore",
    "reconciliation_persistence",
    "OracleRule",
    "OracleSet",
    "OracleSetStatus",
    "RuleConflict",
    "RuleRelationship",
    "ResolutionState",
    "RuleProvenanceSource",
    "ReconciliationPolicy",
    "ReconciliationResult",
    "ReconciliationDiagnostic",
    "DecisionTraceRecord",
]
