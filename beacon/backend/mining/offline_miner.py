"""Deterministic local invariant miner for Python decision functions.

It recognizes assignments made inside ``if``/``elif`` branches, validates the
result against observed traces and the original callable, and therefore gives
the prototype a useful no-API-key mining path.  The Anthropic-based generator
remains the optional cloud implementation for broader legacy languages.
"""

import ast
import hashlib
from typing import Callable

from common.models import CandidateInvariant, TraceEvent, ValidatedInvariant
from .evidence_collector import collect_evidence
from .validator import validate_candidate


def _decision_assignments(statements: list[ast.stmt]) -> list[tuple[ast.expr, str]]:
    rules: list[tuple[ast.expr, str]] = []
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rules.extend(_decision_assignments(statement.body))
            continue
        if not isinstance(statement, ast.If):
            continue
        for nested in statement.body:
            if (isinstance(nested, ast.Assign) and len(nested.targets) == 1
                    and isinstance(nested.targets[0], ast.Name)
                    and nested.targets[0].id == "decision"
                    and isinstance(nested.value, ast.Constant)
                    and isinstance(nested.value.value, str)):
                rules.append((statement.test, nested.value.value.upper()))
        rules.extend(_decision_assignments(statement.orelse))
    return rules


def mine_python_decision_rules(
    source_code: str,
    traces: list[TraceEvent],
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
) -> list[ValidatedInvariant]:
    """Mine and validate decision rules from a Python implementation.

    This intentionally accepts only simple branch-to-decision rules.  Rules
    are still dynamically checked before becoming executable oracles.
    """
    tree = ast.parse(source_code)
    rules = _decision_assignments(tree.body)
    validated: list[ValidatedInvariant] = []

    for condition_node, consequence in rules:
        condition = ast.unparse(condition_node)
        invariant_id = "local-" + hashlib.sha1(condition.encode()).hexdigest()[:8]
        candidate = CandidateInvariant(
            invariant_id=invariant_id,
            condition=condition,
            consequence=consequence,
            severity="critical" if consequence == "REJECT" else "medium",
        )
        evidence = collect_evidence(candidate, traces, corpus_size=len(traces))
        validation = validate_candidate(candidate, legacy_fn, field_bounds, validated)

        # Static branch extraction plus dynamic boundary validation is strong
        # local evidence.  Keep the raw evidence fields in the report pipeline
        # while making successfully verified rules usable without an LLM.
        confidence = 0.95 if validation.boundary_pass_rate >= 0.99 and evidence.evidence_count else 0.0
        invariant = ValidatedInvariant(
            invariant_id=invariant_id,
            condition=condition,
            consequence=consequence,
            severity=candidate.severity,
            confidence=confidence,
            graduated=confidence >= 0.8,
        )
        validated.append(invariant)
    return validated
