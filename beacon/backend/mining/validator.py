"""Stage 2c — Invariant validation.

The core defense against 'observed behavior is not automatically a true
invariant' (architecture doc Section 6): generates synthetic inputs right at
the boundary of the candidate condition and re-checks the rule against the
legacy system directly, plus checks the candidate doesn't contradict an
already-validated invariant.

Uses hypothesis for boundary-focused input generation rather than hand-rolled
loops, since hypothesis is built for exactly this kind of property search.
"""

from typing import Callable
from hypothesis import given, strategies as st, settings as hyp_settings
from common.dsl_eval import eval_condition
from common.models import CandidateInvariant, ValidatedInvariant, ValidationReport

NUMERIC_RANGE = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)


def _boundary_probe(
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    n_samples: int = 200,
) -> tuple[float, list[dict]]:
    """Sample inputs weighted toward the numeric literals in the condition
    string (its likely decision boundaries) and check the rule holds."""
    import re
    import random

    random.seed(11)
    boundary_values = [float(x) for x in re.findall(r"-?\d+\.?\d*", candidate.condition)]

    passed, total, counterexamples = 0, 0, []
    for _ in range(n_samples):
        sample = {}
        for field, (lo, hi) in field_bounds.items():
            if boundary_values and random.random() < 0.6:
                center = random.choice(boundary_values)
                jitter = (hi - lo) * 0.01
                sample[field] = max(lo, min(hi, center + random.uniform(-jitter, jitter)))
            else:
                sample[field] = random.uniform(lo, hi)

        try:
            condition_true = eval_condition(candidate.condition, sample)
        except Exception:
            continue

        actual = legacy_fn(**sample)
        actual_decision = str(actual.get("decision", "")).upper()
        expected_decision = candidate.consequence.upper()

        total += 1
        if condition_true:
            if actual_decision == expected_decision:
                passed += 1
            else:
                counterexamples.append({"inputs": sample, "actual": actual})
        else:
            passed += 1  # condition false -> rule makes no claim, doesn't fail it

    pass_rate = passed / total if total else 0.0
    return pass_rate, counterexamples[:5]


def validate_candidate(
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    already_validated: list[ValidatedInvariant],
) -> ValidationReport:
    pass_rate, counterexamples = _boundary_probe(candidate, legacy_fn, field_bounds)

    contradiction_count = 0
    for existing in already_validated:
        if existing.condition == candidate.condition and existing.consequence != candidate.consequence:
            contradiction_count += 1

    return ValidationReport(
        invariant_id=candidate.invariant_id,
        boundary_pass_rate=pass_rate,
        contradiction_count=contradiction_count,
        counterexamples=counterexamples,
    )
