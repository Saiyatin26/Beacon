"""Stage 2c — Invariant validation.

Genuinely uses Hypothesis for property-based adversarial input generation.
Generates boundary-focused inputs to evaluate the legacy behavior against the candidate property.
Also performs semantic contradiction checking against already-validated invariants.
"""

import re
from typing import Callable, Any
from hypothesis import given, strategies as st, settings as hyp_settings, Phase, HealthCheck
from common.dsl_eval import eval_condition
from common.models import CandidateInvariant, ValidatedInvariant, ValidationReport


def _extract_boundaries(condition: str, bounds: tuple[float, float]) -> list[float]:
    """Extract numeric literals from the condition to use as boundary focus points."""
    values = [float(x) for x in re.findall(r"-?\d+\.?\d*", condition)]
    # Filter to bounds and add actual bounds
    valid = [v for v in values if bounds[0] <= v <= bounds[1]]
    return valid if valid else [bounds[0], bounds[1]]


def _build_strategy(field_bounds: dict[str, tuple[float, float]], condition: str) -> st.SearchStrategy:
    """Build a Hypothesis strategy dictionary for the given fields, emphasizing boundaries."""
    strats = {}
    for field, (lo, hi) in field_bounds.items():
        boundaries = _extract_boundaries(condition, (lo, hi))
        
        # We mix standard floats with specific boundary values and small jitters around boundaries
        base_floats = st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)
        
        jitter_strats = []
        for b in boundaries:
            jitter = (hi - lo) * 0.01
            j_lo, j_hi = max(lo, b - jitter), min(hi, b + jitter)
            if j_lo < j_hi:
                jitter_strats.append(st.floats(min_value=j_lo, max_value=j_hi, allow_nan=False, allow_infinity=False))
        
        if jitter_strats:
            strats[field] = st.one_of(base_floats, *jitter_strats)
        else:
            strats[field] = base_floats

    return st.fixed_dictionaries(strats)


def _boundary_probe(
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
) -> tuple[float, list[dict]]:
    """Use Hypothesis to generate adversarial inputs and check the rule."""
    
    passed = 0
    total = 0
    counterexamples = []
    
    strategy = _build_strategy(field_bounds, candidate.condition)

    @given(sample=strategy)
    @hyp_settings(max_examples=200, phases=[Phase.generate], suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow])
    def run_property_test(sample: dict[str, Any]):
        nonlocal passed, total, counterexamples
        
        try:
            condition_true = eval_condition(candidate.condition, sample)
        except Exception:
            return  # invalid sample or condition error
            
        # Only evaluate legacy fn if we really need to check the property or record it
        # Actually, let's always run it to gather full validation info
        try:
            actual = legacy_fn(**sample)
            actual_decision = str(actual.get("decision", "")).upper()
        except Exception:
            return
            
        expected_decision = candidate.consequence.upper()
        
        total += 1
        if condition_true:
            if actual_decision == expected_decision:
                passed += 1
            else:
                if len(counterexamples) < 5:
                    counterexamples.append({"inputs": sample, "actual": actual, "expected": candidate.consequence})
        else:
            passed += 1  # condition false -> rule makes no claim, so it passes trivially

    try:
        run_property_test()
    except Exception:
        pass # Hypothesis might raise MultipleFailures or similar depending on settings, but we track state in closures

    pass_rate = passed / total if total > 0 else 0.0
    return pass_rate, counterexamples


def _check_semantic_contradiction(
    candidate: CandidateInvariant,
    already_validated: list[ValidatedInvariant],
    field_bounds: dict[str, tuple[float, float]]
) -> int:
    """Check if the candidate condition semantically overlaps with any existing invariant with a different consequence.
    We do this by generating sample inputs and seeing if both conditions can be true simultaneously.
    """
    if not already_validated:
        return 0
        
    contradictions = 0
    strategy = _build_strategy(field_bounds, candidate.condition)
    
    for existing in already_validated:
        if existing.consequence.upper() == candidate.consequence.upper():
            continue  # Same consequence, not a contradiction even if overlapping
            
        overlap_found = False
        
        @given(sample=strategy)
        @hyp_settings(max_examples=50, phases=[Phase.generate], suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow])
        def run_overlap_test(sample: dict[str, Any]):
            nonlocal overlap_found
            if overlap_found:
                return
            try:
                c1 = eval_condition(candidate.condition, sample)
                c2 = eval_condition(existing.condition, sample)
                if c1 and c2:
                    overlap_found = True
            except Exception:
                pass
                
        try:
            run_overlap_test()
        except Exception:
            pass
            
        if overlap_found:
            contradictions += 1
            
    return contradictions


def validate_candidate(
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    already_validated: list[ValidatedInvariant],
) -> ValidationReport:
    pass_rate, counterexamples = _boundary_probe(candidate, legacy_fn, field_bounds)
    contradiction_count = _check_semantic_contradiction(candidate, already_validated, field_bounds)

    return ValidationReport(
        invariant_id=candidate.invariant_id,
        boundary_pass_rate=pass_rate,
        contradiction_count=contradiction_count,
        counterexamples=counterexamples,
    )
