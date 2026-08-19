"""Phase 9 — Shared Test Input Generation and Deterministic Replay.

Generates boundary probes, near-boundary jitters, combinatorial inputs,
diverse random samples, and runtime trace replays with stable input IDs.
"""

import hashlib
import json
import random
from typing import Any, Optional

from oracle.models import (
    CompoundCondition,
    OracleConditionNode,
    OracleDefinition,
    OraclePredicate,
    UnaryCondition,
)
from .models import CertificationTestInput


def _compute_input_id(values: dict[str, Any]) -> str:
    """Computes a deterministic 8-character hex ID from the sorted dictionary of input values."""
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"INP-{h[:8]}"


def _extract_predicates(node: OracleConditionNode) -> list[OraclePredicate]:
    """Recursively collects all leaf comparison predicates from a condition AST."""
    predicates: list[OraclePredicate] = []
    if isinstance(node, OraclePredicate):
        predicates.append(node)
    elif isinstance(node, CompoundCondition):
        for child in node.operands:
            predicates.extend(_extract_predicates(child))
    elif isinstance(node, UnaryCondition):
        predicates.extend(_extract_predicates(node.operand))
    return predicates


def generate_certification_test_suite(
    oracles: list[OracleDefinition],
    field_bounds: dict[str, tuple[float, float]],
    n_diverse_samples: int = 80,
    seed: int = 42,
    runtime_traces: Optional[list[dict[str, Any]]] = None,
    explicit_cases: Optional[list[dict[str, Any]]] = None,
) -> list[CertificationTestInput]:
    """Builds a comprehensive shared test input suite containing:
    1. Exact boundary probes derived from Oracle condition predicates.
    2. Near-boundary jitter probes.
    3. Combinatorial grid inputs for compound conditions.
    4. Diverse uniform property-based samples across field_bounds.
    5. Replayed runtime trace inputs.
    6. Explicitly supplied test cases.
    """
    rng = random.Random(seed)
    test_inputs: list[CertificationTestInput] = []
    seen_inputs: set[str] = set()

    def _add_input(
        values: dict[str, Any],
        origin: str,
        provenance: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
    ):
        # Format types according to field_bounds / integer rounding
        formatted = {}
        for k, v in values.items():
            if "score" in k.lower() or "count" in k.lower() or "id" in k.lower() or "age" in k.lower():
                formatted[k] = int(round(v)) if isinstance(v, (int, float)) else v
            else:
                formatted[k] = v

        inp_id = _compute_input_id(formatted)
        if inp_id not in seen_inputs:
            seen_inputs.add(inp_id)
            test_inputs.append(CertificationTestInput(
                input_id=inp_id,
                values=formatted,
                origin=origin,
                provenance=provenance or {},
                tags=tags or [],
            ))

    # Base mid-points for all bounds
    default_sample = {f: (lo + hi) / 2.0 for f, (lo, hi) in field_bounds.items()}

    # 1. Boundary & Near-Boundary Probing from Oracle ASTs
    for oracle in oracles:
        predicates = _extract_predicates(oracle.condition)
        for pred in predicates:
            var_name = pred.variable
            thresh = pred.value
            if not isinstance(thresh, (int, float)):
                continue

            lo, hi = field_bounds.get(var_name, (0.0, 1000.0))
            is_int = isinstance(thresh, int)
            eps = 1 if is_int else 0.01

            # Exact Boundary Probes: T - eps, T, T + eps
            for delta, label in [(-eps, "below_boundary"), (0, "at_boundary"), (eps, "above_boundary")]:
                val = max(lo, min(hi, thresh + delta))
                sample = dict(default_sample)
                sample[var_name] = val
                _add_input(
                    sample,
                    origin="boundary_probe",
                    provenance={"oracle_id": oracle.oracle_id, "variable": var_name, "threshold": thresh},
                    tags=["boundary", label, oracle.oracle_id],
                )

            # Near-Boundary Jitters: +/- 2% to 5%
            for jitter_pct in [-0.05, -0.02, 0.02, 0.05]:
                delta = thresh * jitter_pct if thresh != 0 else jitter_pct
                val = max(lo, min(hi, thresh + delta))
                sample = dict(default_sample)
                sample[var_name] = val
                _add_input(
                    sample,
                    origin="near_boundary_probe",
                    provenance={"oracle_id": oracle.oracle_id, "variable": var_name, "threshold": thresh},
                    tags=["near_boundary", oracle.oracle_id],
                )

        # Combinatorial Probing for Compound Conditions (2 variables)
        if len(predicates) >= 2:
            p1, p2 = predicates[0], predicates[1]
            if isinstance(p1.value, (int, float)) and isinstance(p2.value, (int, float)):
                v1_name, t1 = p1.variable, p1.value
                v2_name, t2 = p2.variable, p2.value
                eps1 = 1 if isinstance(t1, int) else 0.01
                eps2 = 1 if isinstance(t2, int) else 0.01

                for d1 in [-eps1, eps1]:
                    for d2 in [-eps2, eps2]:
                        sample = dict(default_sample)
                        sample[v1_name] = t1 + d1
                        sample[v2_name] = t2 + d2
                        _add_input(
                            sample,
                            origin="boundary_probe",
                            provenance={"oracle_id": oracle.oracle_id, "type": "combinatorial_boundary"},
                            tags=["combinatorial", oracle.oracle_id],
                        )

    # 2. Diverse Uniform Property-Based Inputs
    for _ in range(n_diverse_samples):
        sample = {f: rng.uniform(lo, hi) for f, (lo, hi) in field_bounds.items()}
        _add_input(sample, origin="diverse_sampling", tags=["diverse_sampling"])

    # 3. Runtime Traces Replay
    if runtime_traces:
        for trace in runtime_traces:
            trace_inputs = trace.get("inputs", trace) if isinstance(trace, dict) else {}
            if trace_inputs:
                _add_input(
                    trace_inputs,
                    origin="runtime_trace",
                    provenance={"trace_id": trace.get("execution_id", "trace")},
                    tags=["runtime_trace"],
                )

    # 4. Explicitly Supplied Cases
    if explicit_cases:
        for case in explicit_cases:
            _add_input(case, origin="explicit_case", tags=["explicit_case"])

    return test_inputs
