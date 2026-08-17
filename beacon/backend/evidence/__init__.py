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

__all__ = [
    "EvidenceType",
    "StaticEvidenceItem",
    "DynamicEvidenceItem",
    "CorrelatedConditionEvidence",
    "UnifiedEvidencePackage",
    "EvidencePackageBuilder",
    "build_evidence_package",
]
