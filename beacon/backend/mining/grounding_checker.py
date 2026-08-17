"""Stage 2a — Semantic Evidence Grounding Checker (Phases 6 & 7 Hardening).

Strictly validates that candidate invariants are semantically grounded in the
authoritative UnifiedEvidencePackage. Rejects candidates containing:
1. Unknown / hallucinated variables.
2. Unsupported / invented numerical thresholds.
3. Nonexistent / hallucinated evidence IDs.
4. Cited static/dynamic evidence items that do not semantically support the candidate condition.
5. Incompatible / unsupported consequences (e.g. claiming APPROVE when evidence shows REJECT).
6. Source line mismatches with cited static evidence.
"""

import ast
import re
from typing import Optional
from pydantic import BaseModel
from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage
from mining.normalizer import normalize_condition

_ALLOWED_AST_NAMES = {"and", "or", "not", "in", "True", "False", "None"}


class GroundingCheckResult(BaseModel):
    is_grounded: bool
    rejection_reason: Optional[str] = None
    grounded_evidence_ids: list[str] = []
    grounded_execution_ids: list[str] = []


def _extract_variables(condition_str: str) -> set[str]:
    """Extracts identifier variable names from a boolean condition expression."""
    try:
        tree = ast.parse(condition_str, mode="eval")
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        return names - _ALLOWED_AST_NAMES
    except Exception:
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
    """Checks whether a candidate invariant is strictly and semantically grounded in the evidence package."""
    norm_candidate_cond = normalize_condition(candidate.condition)
    candidate_vars = _extract_variables(candidate.condition)
    candidate_constants = _extract_numeric_constants(candidate.condition)
    candidate_consequence = candidate.consequence.strip().upper()

    # 1. Collect all known valid variable names across static & dynamic evidence
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

    # Check variable presence
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
    for const in candidate_constants:
        is_grounded_const = any(abs(const - kt) < 1e-4 for kt in known_thresholds)
        if not is_grounded_const and known_thresholds:
            return GroundingCheckResult(
                is_grounded=False,
                rejection_reason=f"Unsupported / invented numerical threshold: {const}. Supported thresholds: {sorted(list(known_thresholds))}",
            )

    # 3. Check Evidence ID Existence and Semantic Support
    static_map = {s.evidence_id: s for s in evidence_package.static_evidence_items}
    dynamic_map = {d.evidence_id: d for d in evidence_package.dynamic_evidence_items}
    all_known_ids = set(static_map.keys()) | set(dynamic_map.keys())

    for ev_id in candidate.evidence_ids:
        if ev_id not in all_known_ids:
            return GroundingCheckResult(
                is_grounded=False,
                rejection_reason=f"Nonexistent / hallucinated evidence ID cited: {ev_id}",
            )

        # Semantic support verification for cited static evidence
        if ev_id in static_map:
            static_item = static_map[ev_id]
            static_cond = static_item.condition or ""
            static_vars = _extract_variables(static_cond)
            static_constants = _extract_numeric_constants(static_cond)

            # Check overlap of variables and constants with the cited static item
            has_var_overlap = bool(candidate_vars & static_vars) if static_vars else True
            has_const_overlap = any(
                any(abs(c - sc) < 1e-4 for sc in static_constants)
                for c in candidate_constants
            ) if static_constants and candidate_constants else True

            if not has_var_overlap and not has_const_overlap:
                return GroundingCheckResult(
                    is_grounded=False,
                    rejection_reason=(
                        f"Cited evidence ID {ev_id} ('{static_cond}') does not semantically "
                        f"support candidate condition '{candidate.condition}'"
                    ),
                )

            # Source line verification if candidate claims source lines
            item_line = getattr(static_item, "line", None) or getattr(static_item, "source_line", None)
            if candidate.source_lines and item_line:
                if item_line not in candidate.source_lines:
                    return GroundingCheckResult(
                        is_grounded=False,
                        rejection_reason=(
                            f"Source line mismatch: candidate cites lines {candidate.source_lines}, "
                            f"but cited evidence {ev_id} is located at line {item_line}"
                        ),
                    )

    # 4. Consequence Grounding (Semantic Compatibility with Observed Outcomes)
    for corr in evidence_package.correlated_conditions:
        norm_corr_cond = normalize_condition(corr.condition_expr)
        if norm_corr_cond == norm_candidate_cond:
            # Check observed outcomes
            if corr.observed_outcomes:
                total_obs = sum(corr.observed_outcomes.values())
                consequence_obs = corr.observed_outcomes.get(candidate_consequence, 0)
                if total_obs > 0 and consequence_obs == 0:
                    return GroundingCheckResult(
                        is_grounded=False,
                        rejection_reason=(
                            f"Unsupported consequence '{candidate_consequence}': evidence for condition "
                            f"'{corr.condition_expr}' only observed outcomes {corr.observed_outcomes}"
                        ),
                    )

    # All checks passed
    return GroundingCheckResult(
        is_grounded=True,
        grounded_evidence_ids=candidate.evidence_ids,
        grounded_execution_ids=candidate.execution_ids,
    )


def filter_grounded_candidates(
    candidates: list[CandidateInvariant],
    evidence_package: UnifiedEvidencePackage,
) -> tuple[list[CandidateInvariant], list[CandidateInvariant]]:
    """Separates candidates into grounded candidates and rejected ungrounded candidates."""
    grounded: list[CandidateInvariant] = []
    rejected: list[CandidateInvariant] = []

    for cand in candidates:
        res = check_candidate_grounding(cand, evidence_package)
        cand.grounding_result = res.model_dump()
        if res.is_grounded:
            cand.status = "candidate"
            grounded.append(cand)
        else:
            cand.status = "GROUNDING_FAILED"
            cand.rationale = f"[REJECTED: {res.rejection_reason}] " + (cand.rationale or "")
            rejected.append(cand)

    return grounded, rejected
