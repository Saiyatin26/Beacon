"""Stage 2c — Invariant Validation.

Routes candidate invariant validation through the Phase 7 Adversarial Validation engine
(backend/mining/adversarial.py) to perform exact boundary, near-boundary, combinatorial
truth-table, and diverse input probing with counterexample detection and minimization.
"""

from typing import Callable, Optional
from common.models import CandidateInvariant, ValidatedInvariant, ValidationReport
from .adversarial import (
    analyze_condition,
    generate_adversarial_inputs,
    minimize_counterexample,
    run_adversarial_validation,
)


def validate_candidate(
    candidate: CandidateInvariant,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    already_validated: list[ValidatedInvariant],
    validation_run_id: Optional[str] = None,
) -> ValidationReport:
    """Validates a candidate invariant against reference behavior using the Phase 7
    adversarial validation engine.
    """
    return run_adversarial_validation(
        candidate=candidate,
        legacy_fn=legacy_fn,
        field_bounds=field_bounds,
        already_validated=already_validated,
        validation_run_id=validation_run_id,
    )
