"""Stage 2c — Adversarial Behavioral Invariant Validation (Phases 7 Hardening).

Implements an independent adversarial validation mechanism that actively attempts to
disprove candidate invariants. Generates boundary, near-boundary, combinatorial truth-table,
and diverse property-based inputs, executes reference behavior, classifies outcomes, detects
and minimizes counterexamples, performs contradiction analysis, and generates structured
ValidationReport models with separated boundary vs diverse metrics and reproducibility metadata.
"""

import ast
from datetime import datetime, timezone
import json
import re
import sys
import uuid
from typing import Any, Callable, Optional

from hypothesis import given, strategies as st, settings as hyp_settings, Phase, HealthCheck
from common.dsl_eval import eval_condition
from common.models import CandidateInvariant, Counterexample, ValidatedInvariant, ValidationReport


# ==============================================================================
# 1. Condition AST Analyzer
# ==============================================================================

class PredicateInfo:
    """Information about a single comparison sub-predicate."""
    def __init__(self, variable: str, operator: str, threshold: float, raw_expr: str):
        self.variable = variable
        self.operator = operator
        self.threshold = threshold
        self.raw_expr = raw_expr


class ConditionAnalysis:
    """Structural breakdown of a candidate condition."""
    def __init__(
        self,
        variables: set[str],
        predicates: list[PredicateInfo],
        logical_connective: Optional[str] = None,
    ):
        self.variables = variables
        self.predicates = predicates
        self.logical_connective = logical_connective  # "and", "or", "not", or None


def analyze_condition(condition_str: str) -> ConditionAnalysis:
    """Parses a condition expression into AST components without domain hardcoding."""
    variables: set[str] = set()
    predicates: list[PredicateInfo] = []
    logical_connective: Optional[str] = None

    try:
        tree = ast.parse(condition_str, mode="eval")
    except Exception:
        var_names = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", condition_str)) - {
            "and", "or", "not", "in", "True", "False", "None"
        }
        return ConditionAnalysis(variables=var_names, predicates=[])

    if isinstance(tree.body, ast.BoolOp):
        if isinstance(tree.body.op, ast.And):
            logical_connective = "and"
        elif isinstance(tree.body.op, ast.Or):
            logical_connective = "or"
    elif isinstance(tree.body, ast.UnaryOp) and isinstance(tree.body.op, ast.Not):
        logical_connective = "not"

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in {"and", "or", "not", "in", "True", "False", "None"}:
                variables.add(node.id)

        elif isinstance(node, ast.Compare):
            if len(node.ops) == 1 and len(node.comparators) == 1:
                left = node.left
                op = node.ops[0]
                right = node.comparators[0]

                var_name = None
                thresh_val = None
                op_symbol = None

                op_map = {
                    ast.Lt: "<",
                    ast.LtE: "<=",
                    ast.Gt: ">",
                    ast.GtE: ">=",
                    ast.Eq: "==",
                    ast.NotEq: "!=",
                }
                op_symbol = op_map.get(type(op))

                if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
                    var_name = left.id
                    if isinstance(right.value, (int, float)):
                        thresh_val = float(right.value)
                elif isinstance(right, ast.Name) and isinstance(left, ast.Constant):
                    var_name = right.id
                    if isinstance(left.value, (int, float)):
                        thresh_val = float(left.value)
                    flip_map = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}
                    if op_symbol:
                        op_symbol = flip_map.get(op_symbol, op_symbol)

                if var_name and thresh_val is not None and op_symbol:
                    raw_expr = ast.unparse(node)
                    predicates.append(PredicateInfo(var_name, op_symbol, thresh_val, raw_expr))

    return ConditionAnalysis(variables=variables, predicates=predicates, logical_connective=logical_connective)


# ==============================================================================
# 2. Adversarial Input Generator
# ==============================================================================

def generate_adversarial_inputs(
    condition: str,
    field_bounds: dict[str, tuple[float, float]],
    target_count: int = 150,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generates boundary inputs, combinatorial truth-table inputs, near-boundary inputs,
    and diverse property inputs.
    
    Returns:
        (boundary_and_combinatorial_inputs, diverse_inputs)
    """
    analysis = analyze_condition(condition)
    boundary_inputs: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    def _add_input(inp_dict: dict[str, Any]):
        complete = {}
        for f, (lo, hi) in field_bounds.items():
            if f in inp_dict:
                val = inp_dict[f]
                clamped = max(lo, min(hi, val))
                complete[f] = int(round(clamped)) if isinstance(val, int) or (lo == int(lo) and hi == int(hi) and clamped == int(clamped)) else float(clamped)
            else:
                mid = (lo + hi) / 2.0
                complete[f] = int(round(mid)) if (lo == int(lo) and hi == int(hi)) else round(mid, 2)
        h = json.dumps(complete, sort_keys=True)
        if h not in seen_hashes:
            seen_hashes.add(h)
            boundary_inputs.append(complete)

    # 1. Exact & Near-Boundary inputs for each predicate
    for pred in analysis.predicates:
        v = pred.variable
        if v not in field_bounds:
            continue
        lo, hi = field_bounds[v]
        T = pred.threshold
        span = hi - lo if hi > lo else 1.0

        eps = 1 if (isinstance(T, int) or T.is_integer()) and span > 10 else max(0.01, span * 0.005)
        jitters = [
            -span * 0.05, -2 * eps, -eps, 0.0, eps, 2 * eps, span * 0.05
        ]

        for j in jitters:
            val = T + j
            _add_input({v: val})

    # 2. Combinatorial Truth-Table Input Generation for compound conditions
    if len(analysis.predicates) >= 2:
        pred_samples: list[list[tuple[str, float]]] = []
        for pred in analysis.predicates:
            v = pred.variable
            if v not in field_bounds:
                continue
            lo, hi = field_bounds[v]
            T = pred.threshold
            span = hi - lo if hi > lo else 1.0
            eps = 1 if (isinstance(T, int) or T.is_integer()) and span > 10 else max(0.01, span * 0.01)

            if pred.operator in ("<", "<="):
                val_true = max(lo, T - eps)
                val_false = min(hi, T + eps)
            elif pred.operator in (">", ">="):
                val_true = min(hi, T + eps)
                val_false = max(lo, T - eps)
            elif pred.operator == "==":
                val_true = T
                val_false = min(hi, T + eps) if T + eps <= hi else max(lo, T - eps)
            else:
                val_true = max(lo, T - eps)
                val_false = min(hi, T + eps)

            pred_samples.append([(v, val_true), (v, val_false)])

        if len(pred_samples) == 2:
            for p1 in pred_samples[0]:
                for p2 in pred_samples[1]:
                    _add_input({p1[0]: p1[1], p2[0]: p2[1]})
        elif len(pred_samples) >= 3:
            for p1 in pred_samples[0]:
                for p2 in pred_samples[1]:
                    for p3 in pred_samples[2]:
                        _add_input({p1[0]: p1[1], p2[0]: p2[1], p3[0]: p3[1]})

    # 3. Diverse inputs via Hypothesis property-based strategies
    diverse_inputs: list[dict[str, Any]] = []
    strats = {}
    for field, (lo, hi) in field_bounds.items():
        if lo == int(lo) and hi == int(hi) and (hi - lo) > 20:
            strats[field] = st.integers(min_value=int(lo), max_value=int(hi))
        else:
            strats[field] = st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)

    hyp_strategy = st.fixed_dictionaries(strats)

    @given(sample=hyp_strategy)
    @hyp_settings(
        max_examples=target_count,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def collect_diverse(sample: dict[str, Any]):
        h = json.dumps(sample, sort_keys=True)
        if h not in seen_hashes:
            seen_hashes.add(h)
            diverse_inputs.append(sample)

    try:
        collect_diverse()
    except Exception:
        pass

    return boundary_inputs, diverse_inputs


# ==============================================================================
# 3. Counterexample Minimization (Shrinking)
# ==============================================================================

def minimize_counterexample(
    failing_input: dict[str, Any],
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    """Shrinks failing counterexample inputs towards baseline / boundary values while
    ensuring the invariant violation is preserved.
    """
    minimized = dict(failing_input)
    expected_decision = candidate.consequence.upper()

    for field, val in list(minimized.items()):
        if not isinstance(val, (int, float)) or field not in field_bounds:
            continue

        lo, hi = field_bounds[field]
        baseline = lo

        current_val = val
        best_val = current_val

        for _ in range(8):
            test_val = (current_val + baseline) / 2.0
            if isinstance(val, int):
                test_val = int(round(test_val))

            candidate_input = dict(minimized)
            candidate_input[field] = test_val

            try:
                if eval_condition(candidate.condition, candidate_input):
                    actual = legacy_fn(**candidate_input)
                    act_dec = str(actual.get("decision", actual.get("result", actual))).upper()
                    if act_dec != expected_decision:
                        best_val = test_val
                        current_val = test_val
                        continue
            except Exception:
                pass

            baseline = test_val

        minimized[field] = best_val

    return minimized


# ==============================================================================
# 4. Semantic Contradiction Checker
# ==============================================================================

def analyze_contradictions(
    candidate: CandidateInvariant,
    already_validated: list[ValidatedInvariant],
    field_bounds: dict[str, tuple[float, float]],
    test_inputs: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    """Identifies overlapping conditions between candidate and existing invariants
    where consequences conflict.
    """
    if not already_validated:
        return 0, []

    contradiction_count = 0
    contradiction_details: list[dict[str, Any]] = []

    for existing in already_validated:
        if existing.consequence.strip().upper() == candidate.consequence.strip().upper():
            continue  # Compatible consequence

        overlapping_samples: list[dict[str, Any]] = []
        for sample in test_inputs:
            try:
                c_candidate = eval_condition(candidate.condition, sample)
                c_existing = eval_condition(existing.condition, sample)
                if c_candidate and c_existing:
                    overlapping_samples.append(sample)
                    if len(overlapping_samples) >= 3:
                        break
            except Exception:
                pass

        if overlapping_samples:
            contradiction_count += 1
            contradiction_details.append({
                "candidate_id": candidate.invariant_id,
                "conflicting_invariant_id": existing.invariant_id,
                "candidate_condition": candidate.condition,
                "candidate_consequence": candidate.consequence,
                "conflicting_condition": existing.condition,
                "conflicting_consequence": existing.consequence,
                "overlapping_samples": overlapping_samples,
            })

    return contradiction_count, contradiction_details


# ==============================================================================
# 5. Full Adversarial Validation Engine
# ==============================================================================

def run_adversarial_validation(
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    already_validated: list[ValidatedInvariant],
    validation_run_id: Optional[str] = None,
) -> ValidationReport:
    """Executes the complete Phase 7 adversarial validation pipeline on a candidate invariant."""
    run_id = validation_run_id or f"VAL-{uuid.uuid4().hex[:6]}"
    now_ts = datetime.now(timezone.utc).isoformat()

    # 1. Generate boundary, combinatorial, near-boundary, and diverse inputs
    boundary_inputs, diverse_inputs = generate_adversarial_inputs(
        condition=candidate.condition,
        field_bounds=field_bounds,
        target_count=100,
    )

    all_probes = [(inp, True) for inp in boundary_inputs] + [(inp, False) for inp in diverse_inputs]

    condition_true_count = 0
    condition_false_count = 0
    total_probes = len(all_probes)
    passed_probes = 0
    failed_probes = 0
    execution_errors = 0

    # Separated boundary and diverse metric counters
    boundary_probes_total = len(boundary_inputs)
    boundary_probes_true = 0
    boundary_probes_passed = 0
    boundary_probes_failed = 0

    diverse_probes_total = len(diverse_inputs)
    diverse_probes_true = 0
    diverse_probes_passed = 0
    diverse_probes_failed = 0

    counterexamples: list[Counterexample] = []
    expected_decision = candidate.consequence.strip().upper()

    # 2. Execute legacy reference implementation & evaluate property
    for sample, is_boundary in all_probes:
        try:
            cond_holds = eval_condition(candidate.condition, sample)
        except Exception:
            execution_errors += 1
            continue

        if cond_holds:
            condition_true_count += 1
            if is_boundary:
                boundary_probes_true += 1
            else:
                diverse_probes_true += 1

            try:
                actual_raw = legacy_fn(**sample)
                if isinstance(actual_raw, dict):
                    if "decision" in actual_raw:
                        actual_dec = str(actual_raw["decision"]).upper()
                    elif "result" in actual_raw:
                        actual_dec = str(actual_raw["result"]).upper()
                    elif len(actual_raw) == 1:
                        actual_dec = str(next(iter(actual_raw.values()))).upper()
                    else:
                        actual_dec = str(actual_raw).upper()
                else:
                    actual_dec = str(actual_raw).upper()
            except Exception as exc:
                execution_errors += 1
                if is_boundary:
                    boundary_probes_failed += 1
                else:
                    diverse_probes_failed += 1
                if len(counterexamples) < 5:
                    counterexamples.append(Counterexample(
                        candidate_id=candidate.invariant_id,
                        validation_run_id=run_id,
                        inputs=sample,
                        condition_result=True,
                        expected_result=expected_decision,
                        actual_result=f"ERROR: {exc}",
                        failure_type="EXECUTION_ERROR",
                        evidence_ids=candidate.evidence_ids,
                        execution_ids=candidate.execution_ids,
                        timestamp=now_ts,
                    ))
                continue

            if actual_dec == expected_decision:
                passed_probes += 1
                if is_boundary:
                    boundary_probes_passed += 1
                else:
                    diverse_probes_passed += 1
            else:
                failed_probes += 1
                if is_boundary:
                    boundary_probes_failed += 1
                else:
                    diverse_probes_failed += 1

                # 3. Minimize / shrink counterexample
                minimized_sample = minimize_counterexample(sample, candidate, legacy_fn, field_bounds)
                if len(counterexamples) < 10:
                    counterexamples.append(Counterexample(
                        candidate_id=candidate.invariant_id,
                        validation_run_id=run_id,
                        inputs=minimized_sample,
                        condition_result=True,
                        expected_result=expected_decision,
                        actual_result=actual_dec,
                        failure_type="VIOLATION",
                        evidence_ids=candidate.evidence_ids,
                        execution_ids=candidate.execution_ids,
                        timestamp=now_ts,
                    ))
        else:
            condition_false_count += 1

    # 4. Compute Separated Metrics & Coverage
    condition_coverage = (condition_true_count / total_probes) if total_probes > 0 else 0.0
    
    # Boundary pass rate strictly from boundary probes
    if boundary_probes_true > 0:
        boundary_pass_rate = boundary_probes_passed / boundary_probes_true
    else:
        boundary_pass_rate = 0.0

    # Diverse input pass rate strictly from diverse probes
    if diverse_probes_true > 0:
        diverse_input_pass_rate = diverse_probes_passed / diverse_probes_true
    else:
        diverse_input_pass_rate = 0.0

    # Overall property pass rate
    if condition_true_count > 0:
        overall_property_pass_rate = passed_probes / condition_true_count
    else:
        overall_property_pass_rate = 0.0

    # 5. Semantic Contradiction Analysis
    all_sample_dicts = [p[0] for p in all_probes]
    contra_count, contra_details = analyze_contradictions(
        candidate=candidate,
        already_validated=already_validated,
        field_bounds=field_bounds,
        test_inputs=all_sample_dicts,
    )

    # 6. Status determination
    if failed_probes > 0:
        status = "INVALIDATED"
    elif condition_true_count == 0:
        status = "UNCONFIRMED"
    elif boundary_pass_rate < 1.0 or overall_property_pass_rate < 1.0:
        status = "INVALIDATED"
    else:
        status = "VALIDATED"

    # Convert counterexamples to dict for JSON serializability
    ce_dicts = [ce.model_dump() for ce in counterexamples]

    # Reproducibility Metadata
    reproducibility = {
        "validation_run_id": run_id,
        "candidate_id": candidate.invariant_id,
        "generation_method": candidate.generation_method,
        "hypothesis_max_examples": 100,
        "boundary_probes_generated": boundary_probes_total,
        "diverse_probes_generated": diverse_probes_total,
        "python_version": sys.version.split()[0],
        "timestamp": now_ts,
    }

    report = ValidationReport(
        invariant_id=candidate.invariant_id,
        validation_run_id=run_id,
        overall_property_pass_rate=round(overall_property_pass_rate, 4),
        boundary_pass_rate=round(boundary_pass_rate, 4),
        diverse_input_pass_rate=round(diverse_input_pass_rate, 4),
        contradiction_count=contra_count,
        counterexamples=ce_dicts,
        condition_true_count=condition_true_count,
        condition_false_count=condition_false_count,
        total_probes=total_probes,
        passed_probes=passed_probes,
        failed_probes=failed_probes,
        execution_errors=execution_errors,
        boundary_tests_count=boundary_probes_total,
        boundary_probes_total=boundary_probes_total,
        boundary_probes_true=boundary_probes_true,
        boundary_probes_passed=boundary_probes_passed,
        boundary_probes_failed=boundary_probes_failed,
        diverse_tests_count=diverse_probes_total,
        diverse_probes_total=diverse_probes_total,
        diverse_probes_true=diverse_probes_true,
        diverse_probes_passed=diverse_probes_passed,
        diverse_probes_failed=diverse_probes_failed,
        condition_coverage=round(condition_coverage, 4),
        contradiction_details=contra_details,
        evidence_ids=candidate.evidence_ids,
        execution_ids=candidate.execution_ids,
        reproducibility=reproducibility,
        timestamp=now_ts,
        status=status,
    )

    # Attach full validation provenance to candidate
    candidate.validation_result = report.model_dump()
    candidate.status = status

    return report
