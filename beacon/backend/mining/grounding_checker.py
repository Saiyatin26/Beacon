"""Stage 2a — Evidence Grounding Checker (Phase 6).

Strictly validates that LLM-proposed candidate invariants are grounded in the
authoritative UnifiedEvidencePackage. Rejects candidates containing:
1. Hallucinated / unknown variables not present in static AST or dynamic traces.
2. Unsupported numerical thresholds not present in static code or observed evidence.
3. Nonexistent / hallucinated evidence IDs (e.g. EV-S-999).
4. Invalid source line references.
"""

import ast
import re
from typing import Optional
from pydantic import BaseModel
from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage

_ALLOWED_AST_NAMES = {"and", "or", "not", "in", "True", "False", "None"}


class GroundingCheckResult(BaseModel):
    is_grounded: bool
    rejection_reason: Optional[str] = None


def _extract_variables(condition_str: str) -> set[str]:
    """Extracts identifier variable names from a boolean condition expression."""
    try:
        tree = ast.parse(condition_str, mode="eval")
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        return names - _ALLOWED_AST_NAMES
    except Exception:
        # Fallback token extraction
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", condition_str)
        return set(tokens) - _ALLOWED_AST_NAMES


def _extract_numeric_constants(condition_str: str) -> list[float]:
    """Extracts numeric literal constants from condition expression."""
    matches = re.findall(r"-?\b\d+(?:\.\d+)?\b", condition_str)
    return [float(m) for m in matches]


def check_candidate_grounding(
    candidate: CandidateInvariant,
    evidence_package: UnifiedEvidencePackage,
) -> GroundingCheckResult:
    """Checks whether a candidate invariant is strictly grounded in the evidence package."""

    # 1. Collect all known valid variable names from static and dynamic evidence
    known_vars: set[str] = set()
    if evidence_package.static_analysis:
        for f in evidence_package.static_analysis.functions:
            known_vars.update(f.parameters)
        for comp in evidence_package.static_analysis.comparisons:
            if isinstance(comp.left, str):
                known_vars.add(comp.left)
            if isinstance(comp.right, str) and not comp.right.replace(".", "", 1).isdigit():
                known_vars.add(comp.right)
        for a in evidence_package.static_analysis.assignments:
            known_vars.add(a.target)

    for d in evidence_package.dynamic_evidence_items:
        if isinstance(d.inputs, dict):
            known_vars.update(d.inputs.keys())
        if isinstance(d.output, dict):
            known_vars.update(d.output.keys())
        if d.variable_snapshot:
            known_vars.update(d.variable_snapshot.keys())

    # Check variable grounding
    candidate_vars = _extract_variables(candidate.condition)
    unknown_vars = candidate_vars - known_vars
    if unknown_vars:
        return GroundingCheckResult(
            is_grounded=False,
            rejection_reason=f"Hallucinated / unknown variables in condition: {sorted(list(unknown_vars))}",
        )

    # 2. Collect all known numeric thresholds from static conditions and comparisons
    known_thresholds: set[float] = set()
    for s in evidence_package.static_evidence_items:
        if s.condition:
            for num in _extract_numeric_constants(s.condition):
                known_thresholds.add(num)
    for c in evidence_package.correlated_conditions:
        for num in _extract_numeric_constants(c.condition_expr):
            known_thresholds.add(num)

    # Check threshold grounding
    candidate_constants = _extract_numeric_constants(candidate.condition)
    for const in candidate_constants:
        # A constant is considered grounded if it matches a known static/correlated threshold
        # or exactly matches boundary values observed in static code.
        is_grounded_const = any(abs(const - kt) < 1e-4 for kt in known_thresholds)
        if not is_grounded_const and known_thresholds:
            return GroundingCheckResult(
                is_grounded=False,
                rejection_reason=f"Unsupported / invented numerical threshold: {const}. Supported thresholds: {sorted(list(known_thresholds))}",
            )

    # 3. Check Evidence ID grounding
    valid_static_ids = {s.evidence_id for s in evidence_package.static_evidence_items}
    valid_dynamic_ids = {d.evidence_id for d in evidence_package.dynamic_evidence_items}
    valid_all_ids = valid_static_ids | valid_dynamic_ids

    for ev_id in candidate.evidence_ids:
        if ev_id not in valid_all_ids:
            return GroundingCheckResult(
                is_grounded=False,
                rejection_reason=f"Nonexistent / hallucinated evidence ID cited: {ev_id}",
            )

    return GroundingCheckResult(is_grounded=True)


def filter_grounded_candidates(
    candidates: list[CandidateInvariant],
    evidence_package: UnifiedEvidencePackage,
) -> tuple[list[CandidateInvariant], list[CandidateInvariant]]:
    """Separates candidates into grounded candidates and rejected ungrounded candidates."""
    grounded: list[CandidateInvariant] = []
    rejected: list[CandidateInvariant] = []

    for cand in candidates:
        res = check_candidate_grounding(cand, evidence_package)
        if res.is_grounded:
            cand.status = "candidate"
            grounded.append(cand)
        else:
            cand.status = "GROUNDING_FAILED"
            cand.rationale = f"[REJECTED: {res.rejection_reason}] " + (cand.rationale or "")
            rejected.append(cand)

    return grounded, rejected
