"""Stage 2a — Candidate Normalizer (Phase 6).

Canonicalizes boolean condition expressions into a standard representation so that
semantically equivalent expressions (such as commutative conjunctions/disjunctions
'credit_score < 600 and debt_ratio > 0.4' vs 'debt_ratio > 0.4 and credit_score < 600')
map to identical strings without building a heavy theorem prover.
"""

import ast
import re
from typing import Optional
from common.models import CandidateInvariant


def _canonicalize_ast_node(node: ast.AST) -> ast.AST:
    """Recursively canonicalizes commutative boolean operations (And / Or)."""
    if isinstance(node, ast.BoolOp):
        canonical_values = [_canonicalize_ast_node(v) for v in node.values]
        # Sort sub-expressions by their unparsed text representation
        canonical_values.sort(key=lambda n: ast.unparse(n))
        node.values = canonical_values
        return node
    elif isinstance(node, ast.UnaryOp):
        node.operand = _canonicalize_ast_node(node.operand)
        return node
    return node


def normalize_condition(condition_str: str) -> str:
    """Normalizes a condition string to its canonical formatted equivalent."""
    if not condition_str or not condition_str.strip():
        return ""

    raw = condition_str.strip()

    # Pre-clean boolean operator tokens
    cleaned = re.sub(r"\bAND\b", "and", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bOR\b", "or", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bNOT\b", "not", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("&&", " and ").replace("||", " or ")

    try:
        tree = ast.parse(cleaned, mode="eval")
        canonical_tree = _canonicalize_ast_node(tree.body)
        normalized = ast.unparse(canonical_tree)
        # Clean extra outer parentheses if redundant
        return normalized.strip()
    except Exception:
        # Fallback to token-level sorting for simple 'and' chains if AST parsing fails
        parts = [p.strip() for p in cleaned.split(" and ")]
        parts.sort()
        return " and ".join(parts)


def normalize_candidate(candidate: CandidateInvariant) -> CandidateInvariant:
    """Returns a new CandidateInvariant with canonicalized condition and consequence."""
    norm_cond = normalize_condition(candidate.condition)
    norm_consequence = candidate.consequence.strip().upper() if candidate.consequence else ""
    
    return CandidateInvariant(
        invariant_id=candidate.invariant_id,
        condition=norm_cond,
        raw_condition=candidate.raw_condition or candidate.condition,
        consequence=norm_consequence,
        source_file=candidate.source_file,
        source_lines=sorted(list(set(candidate.source_lines))),
        severity=candidate.severity,
        evidence_ids=list(dict.fromkeys(candidate.evidence_ids)),
        execution_ids=list(dict.fromkeys(candidate.execution_ids)),
        generation_method=candidate.generation_method,
        timestamp=candidate.timestamp,
        rationale=candidate.rationale,
        confidence_components=candidate.confidence_components,
        grounding_result=candidate.grounding_result,
        validation_result=candidate.validation_result,
        reproducibility=candidate.reproducibility,
        status=candidate.status,
    )
