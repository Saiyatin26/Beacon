"""Stage 2a — Evidence Relevance Selector (Phase 6).

Deterministically ranks and selects the most salient static, dynamic, and correlated
evidence from a UnifiedEvidencePackage to build a high-signal LLM context within
prompt token budgets.

Important distinction:
- Evidence Relevance Score: Prioritizes which evidence is most informative to present to the LLM.
- Invariant Confidence Score: Downstream independent mathematical validation of candidate invariants.
"""

from typing import Optional
from pydantic import BaseModel, Field
from evidence.models import (
    CorrelatedConditionEvidence,
    DynamicEvidenceItem,
    StaticEvidenceItem,
    UnifiedEvidencePackage,
)


class SelectedEvidenceContext(BaseModel):
    """Container for relevance-filtered evidence ready for LLM prompt construction."""
    source_file: str
    language: str
    correlated_conditions: list[CorrelatedConditionEvidence] = Field(default_factory=list)
    static_items: list[StaticEvidenceItem] = Field(default_factory=list)
    dynamic_items: list[DynamicEvidenceItem] = Field(default_factory=list)
    relevance_scores: dict[str, float] = Field(default_factory=dict)


def score_evidence_relevance(correlated: CorrelatedConditionEvidence) -> float:
    """Computes a deterministic relevance score in [0.0, 1.0] for a correlated condition."""
    # 1. Static Support (presence of static AST anchor)
    static_score = 1.0 if correlated.static_support else 0.2

    # 2. Runtime Observation Frequency
    runtime_score = min(correlated.runtime_observations / 50.0, 1.0)

    # 3. Input Diversity
    diversity_score = min(correlated.unique_inputs / 15.0, 1.0)

    # 4. Boundary Observations
    boundary_score = min(correlated.boundary_cases / 5.0, 1.0)

    # 5. Outcome Consistency (Purity of observed decisions)
    outcomes = correlated.observed_outcomes
    total_outcomes = sum(outcomes.values())
    if total_outcomes > 0:
        dominant_count = max(outcomes.values())
        purity_score = dominant_count / total_outcomes
    else:
        purity_score = 0.0

    # Weighted relevance ranking (weights sum to 1.0)
    relevance = (
        0.25 * static_score
        + 0.25 * runtime_score
        + 0.20 * diversity_score
        + 0.15 * boundary_score
        + 0.15 * purity_score
    )
    return round(min(1.0, max(0.0, relevance)), 4)


def select_relevant_evidence(
    evidence_package: UnifiedEvidencePackage,
    max_correlated: int = 10,
    max_static: int = 15,
    max_dynamic: int = 25,
) -> SelectedEvidenceContext:
    """Selects the top-K most relevant evidence elements from a UnifiedEvidencePackage."""
    
    # 1. Score and rank all correlated condition items
    scored_conditions: list[tuple[float, CorrelatedConditionEvidence]] = []
    relevance_map: dict[str, float] = {}

    for corr in evidence_package.correlated_conditions:
        score = score_evidence_relevance(corr)
        scored_conditions.append((score, corr))
        relevance_map[corr.condition_expr] = score

    # Sort descending by relevance score, then by condition string for stable determinism
    scored_conditions.sort(key=lambda x: (-x[0], x[1].condition_expr))
    selected_correlated = [item[1] for item in scored_conditions[:max_correlated]]

    # 2. Select relevant static items (prioritize items tied to selected correlated conditions)
    selected_static_exprs = {c.condition_expr for c in selected_correlated if c.condition_expr}
    priority_static: list[StaticEvidenceItem] = []
    other_static: list[StaticEvidenceItem] = []

    for s_item in evidence_package.static_evidence_items:
        if s_item.condition in selected_static_exprs:
            priority_static.append(s_item)
        else:
            other_static.append(s_item)

    selected_static = (priority_static + other_static)[:max_static]

    # 3. Select representative dynamic traces
    # Collect execution IDs from selected correlated conditions first
    priority_exec_ids = set()
    for corr in selected_correlated:
        for exec_id in corr.execution_ids[:3]:
            priority_exec_ids.add(exec_id)

    priority_dynamic: list[DynamicEvidenceItem] = []
    other_dynamic: list[DynamicEvidenceItem] = []

    for d_item in evidence_package.dynamic_evidence_items:
        if d_item.execution_id in priority_exec_ids:
            priority_dynamic.append(d_item)
        else:
            other_dynamic.append(d_item)

    selected_dynamic = (priority_dynamic + other_dynamic)[:max_dynamic]

    return SelectedEvidenceContext(
        source_file=evidence_package.source_file,
        language=evidence_package.language,
        correlated_conditions=selected_correlated,
        static_items=selected_static,
        dynamic_items=selected_dynamic,
        relevance_scores=relevance_map,
    )
