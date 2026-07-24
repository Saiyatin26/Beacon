"""Stage 3 — Generic oracle interpreter.

Executes an Oracle's 'condition implies decision == X' property directly
against a given implementation function, for a batch of generated inputs.
This is what makes the oracle language-agnostic in the demo: the same
interpreter checks the legacy Python stub and the modernized Python stub here;
in a full build, this would dispatch to per-language runners (Java/Rust via
Docker, per architecture doc Section 5) behind the same interface.
"""

import random
from typing import Callable
from common.dsl_eval import eval_condition
from common.models import Oracle


def _condition_and_expected(oracle: Oracle) -> tuple[str, str]:
    condition, rest = oracle.property.split(") implies (decision == '")
    condition = condition.lstrip("(")
    expected = rest.rstrip("')")
    return condition, expected


def run_oracle(
    oracle: Oracle,
    impl_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    n_samples: int = 100,
    seed: int = 3,
) -> dict:
    """Runs one oracle against one implementation. Returns pass/fail summary
    plus the first counterexample found, if any."""
    condition, expected = _condition_and_expected(oracle)
    rng = random.Random(seed)

    checked, violated = 0, 0
    first_counterexample = None

    for _ in range(n_samples):
        sample = {f: rng.uniform(lo, hi) for f, (lo, hi) in field_bounds.items()}
        if "credit_score" in sample:
            sample["credit_score"] = int(sample["credit_score"])

        try:
            condition_true = eval_condition(condition, sample)
        except Exception:
            continue
        if not condition_true:
            continue

        checked += 1
        actual = impl_fn(**sample)
        actual_decision = str(actual.get("decision", "")).upper()

        if actual_decision != expected:
            violated += 1
            if first_counterexample is None:
                first_counterexample = {"inputs": sample, "actual": actual_decision, "expected": expected}

    passed = checked - violated
    return {
        "invariant_id": oracle.invariant_id,
        "checked": checked,
        "violated": violated,
        "passed": passed,
        "pass_i": 1 if violated == 0 and checked > 0 else 0,
        "counterexample": first_counterexample,
    }
