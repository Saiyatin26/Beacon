"""BEACON Evidence Module (Phase 5).

Combines static source-code analysis facts (Phase 3) and dynamic runtime trace
events (Phase 4) into a unified, traceable, and machine-readable evidence model
(UnifiedEvidencePackage) for invariant reasoning.
"""

from .models import (
    EvidenceType,
    StaticEvidenceItem,
    DynamicEvidenceItem,
    CorrelatedConditionEvidence,
    UnifiedEvidencePackage,
)
from .builder import EvidencePackageBuilder, build_evidence_package
from .dossier_models import (
    EvidenceDossier,
    SourceEvidence,
    ImplementationEvidence,
    OracleEvidence,
    OracleEvidenceItem,
    ExecutionEvidence,
    CounterexampleEvidenceItem,
    PolicyEvidence,
    ProvenanceEvidence,
    CryptographicEvidence,
    EvidenceCompletenessReport,
    AuditorNote,
    EvidenceTraceNode,
    StructuredExplanation,
)
from .dossier_builder import build_evidence_dossier, check_evidence_completeness
from .explainer import generate_structured_explanation
from .traceability_graph import build_traceability_graph
from .notes_store import auditor_notes_store, AuditorNotesStore
from .run_comparator import compare_certification_runs

__all__ = [
    "EvidenceType",
    "StaticEvidenceItem",
    "DynamicEvidenceItem",
    "CorrelatedConditionEvidence",
    "UnifiedEvidencePackage",
    "EvidencePackageBuilder",
    "build_evidence_package",
    "EvidenceDossier",
    "SourceEvidence",
    "ImplementationEvidence",
    "OracleEvidence",
    "OracleEvidenceItem",
    "ExecutionEvidence",
    "CounterexampleEvidenceItem",
    "PolicyEvidence",
    "ProvenanceEvidence",
    "CryptographicEvidence",
    "EvidenceCompletenessReport",
    "AuditorNote",
    "EvidenceTraceNode",
    "StructuredExplanation",
    "build_evidence_dossier",
    "check_evidence_completeness",
    "generate_structured_explanation",
    "build_traceability_graph",
    "auditor_notes_store",
    "AuditorNotesStore",
    "compare_certification_runs",
]
