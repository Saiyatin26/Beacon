"""Stage 1 Unified Evidence Data Models (Phase 5).

TECHNICAL MECHANISM DOCUMENTATION (Patent & Architecture Reference):
==================================================================
Problem Solved:
  Static analysis alone yields candidate rules without runtime proof, while
  dynamic execution traces alone observe runtime behaviors without source-code provenance.
  Neither alone provides an auditable, quantifiable basis for certifying behavioral equivalence.

How It Works:
  This module defines the unified data structures that fuse static source facts
  (AST conditionals, comparisons, source locations) and dynamic runtime observations
  (inputs, outputs, line executions, branch results) into normalized evidence items.

Inputs:
  - StaticAnalysisResult (AST functions, conditions, comparisons, source locations)
  - TraceEvent list (runtime execution IDs, inputs, outputs, executed branch outcomes)

Outputs:
  - StaticEvidenceItem (EV-S-xxx)
  - DynamicEvidenceItem (EV-D-xxx)
  - CorrelatedConditionEvidence (evidence strength metrics: static support, runtime observations,
    unique inputs, boundary cases, contradictions, source locations, execution IDs)
  - UnifiedEvidencePackage (complete serializable payload ready for Stage 2 invariant mining)

Algorithm:
  Unified Evidence Synthesis & Cross-Correlational Mapping.

Why It Is Needed:
  Serves as the traceable, explainable foundation connecting legacy source code to runtime behavior,
  enabling Stage 2 invariant candidate generation and confidence scoring without bypassing empirical evidence.
"""

from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

from common.models import SourceLocation, StaticAnalysisResult, TraceEvent

EvidenceType = Literal[
    "STATIC_CONDITION",
    "STATIC_COMPARISON",
    "STATIC_ASSIGNMENT",
    "RUNTIME_OBSERVATION",
    "RUNTIME_BRANCH_RESULT",
]


class StaticEvidenceItem(BaseModel):
    """Normalized static fact extracted from AST analysis."""
    evidence_id: str  # e.g. "EV-S-001"
    type: EvidenceType = "STATIC_CONDITION"
    file: str
    line: int
    column: Optional[int] = None
    function: Optional[str] = None
    condition: str
    operator: Optional[str] = None
    left: Optional[str] = None
    right: Optional[Any] = None
    strength: float = 0.7  # Static evidence weight metadata
    source_location_id: Optional[str] = None  # e.g. "legacy_source.py:14"


class DynamicEvidenceItem(BaseModel):
    """Normalized dynamic fact captured during runtime execution."""
    evidence_id: str  # e.g. "EV-D-001"
    type: EvidenceType = "RUNTIME_OBSERVATION"
    execution_id: str  # e.g. "EX-001"
    timestamp: str
    function: Optional[str] = None
    inputs: dict
    output: dict
    branch_results: dict[str, bool] = Field(default_factory=dict)
    variable_snapshot: dict = Field(default_factory=dict)


class CorrelatedConditionEvidence(BaseModel):
    """Cross-correlated static + dynamic evidence for a specific condition.

    Aggregates runtime observations against static AST rules to calculate features
    required for Stage 2 confidence scoring.
    """
    condition_expr: str  # e.g. "credit_score < 600" or "credit_score < 600 and debt_ratio > 0.4"
    static_item: Optional[StaticEvidenceItem] = None
    dynamic_items: list[DynamicEvidenceItem] = Field(default_factory=list)
    static_support: bool = False
    runtime_observations: int = 0
    unique_inputs: int = 0
    boundary_cases: int = 0
    contradictions: int = 0
    source_locations: list[str] = Field(default_factory=list)  # ["file:line"]
    execution_ids: list[str] = Field(default_factory=list)      # ["EX-001", "EX-002"]
    observed_outcomes: dict[str, int] = Field(default_factory=dict)  # {"REJECT": 12, "APPROVE": 0}


import hashlib
import json


def compute_evidence_package_hash(package: UnifiedEvidencePackage) -> str:
    """Computes a deterministic 64-character SHA-256 canonical hash across all evidence components:
    static analysis, runtime traces, static facts, dynamic facts, correlated facts, and metadata.
    """
    canonical_dict = {
        "package_id": package.package_id,
        "project_id": package.project_id,
        "source_file": package.source_file,
        "language": package.language,
        "static_analysis": package.static_analysis.model_dump(mode="json") if package.static_analysis else None,
        "runtime_traces": [t.model_dump(mode="json") for t in package.runtime_traces],
        "static_evidence_items": [s.model_dump(mode="json") for s in sorted(package.static_evidence_items, key=lambda x: (x.evidence_id, x.file, x.line))],
        "dynamic_evidence_items": [d.model_dump(mode="json") for d in sorted(package.dynamic_evidence_items, key=lambda x: (x.evidence_id, x.execution_id))],
        "correlated_conditions": [c.model_dump(mode="json") for c in sorted(package.correlated_conditions, key=lambda x: x.condition_expr)],
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class UnifiedEvidencePackage(BaseModel):
    """Container combining static facts, dynamic traces, and correlated evidence."""
    package_id: str
    project_id: str = "beacon-project"
    source_file: str
    language: str = "python"
    timestamp: str
    static_analysis: Optional[StaticAnalysisResult] = None
    runtime_traces: list[TraceEvent] = Field(default_factory=list)
    static_evidence_items: list[StaticEvidenceItem] = Field(default_factory=list)
    dynamic_evidence_items: list[DynamicEvidenceItem] = Field(default_factory=list)
    correlated_conditions: list[CorrelatedConditionEvidence] = Field(default_factory=list)
    evidence_package_hash: str = ""

    def compute_hash(self) -> str:
        """Computes deterministic canonical SHA-256 hash of this evidence package."""
        h = compute_evidence_package_hash(self)
        object.__setattr__(self, "evidence_package_hash", h)
        return h
