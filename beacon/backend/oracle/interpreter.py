"""Stage 3 / Phase 8 — Generic Oracle Interpreter.

Executes an Oracle's behavioral specification directly against a given implementation
function for a batch of generated inputs using the language-independent evaluator.
"""

import random
from typing import Any, Callable, Union

from .evaluator import evaluate_oracle
from .models import OracleDefinition


def run_oracle(
    oracle: Union[OracleDefinition, Any],
    impl_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    n_samples: int = 100,
    seed: int = 3,
) -> dict:
    """Runs one oracle against an implementation function using generic I/O evaluation.
    Returns pass/fail summary and counterexample if violated.
    """
    rng = random.Random(seed)

    checked, violated = 0, 0
    first_counterexample = None

    for _ in range(n_samples):
        sample = {
            f: (int(rng.uniform(lo, hi)) if (isinstance(lo, int) and isinstance(hi, int)) else rng.uniform(lo, hi))
            for f, (lo, hi) in field_bounds.items()
        }

        # Execute target implementation
        try:
            actual_output = impl_fn(**sample)
        except Exception as exc:
            actual_output = {"decision": "ERROR", "error": str(exc)}

        # Evaluate language-independent oracle
        report = evaluate_oracle(oracle, inputs=sample, outputs=actual_output)

        if report.status == "NOT_APPLICABLE":
            continue

        checked += 1

        if report.status in ("FAIL", "EVALUATION_ERROR", "INVALID_INPUT"):
            violated += 1
            if first_counterexample is None:
                first_counterexample = {
                    "inputs": sample,
                    "actual": actual_output.get("decision", "ERROR") if isinstance(actual_output, dict) else str(actual_output),
                    "expected": oracle.consequence.value if hasattr(oracle, "consequence") else "UNKNOWN",
                }

    passed = checked - violated
    inv_id = getattr(oracle, "invariant_id", getattr(oracle, "oracle_id", "UNKNOWN"))

    return {
        "invariant_id": inv_id,
        "oracle_id": getattr(oracle, "oracle_id", inv_id),
        "checked": checked,
        "violated": violated,
        "passed": passed,
        "pass_i": 1 if violated == 0 and checked > 0 else 0,
        "counterexample": first_counterexample,
    }
