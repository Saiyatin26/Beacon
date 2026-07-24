"""Stage 5 — Production drift monitor.

Re-runs the same oracle set from Stage 3/4 against sampled post-deployment
traffic (architecture doc Section 7.5) and alerts when the rolling score drops
below the certified go-live baseline by more than the configured delta.
"""

from datetime import datetime, timezone
from typing import Callable
from common.config import settings
from common.db import drift_samples_col
from common.models import Oracle, DriftSample
from oracle.interpreter import run_oracle
from certification.scorer import equivalence_score


def check_drift(
    oracles: list[Oracle],
    deployed_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    baseline_score: float,
) -> DriftSample:
    oracles_by_id = {o.invariant_id: o for o in oracles}
    results = [run_oracle(o, deployed_fn, field_bounds) for o in oracles]
    current_score = equivalence_score(results, oracles_by_id)

    delta_pct = (baseline_score - current_score) * 100
    alert = delta_pct > settings.drift_alert_delta_pct

    sample = DriftSample(
        run_timestamp=datetime.now(timezone.utc).isoformat(),
        equivalence_score=current_score,
        baseline_score=baseline_score,
        delta_pct=round(delta_pct, 2),
        alert=alert,
    )
    drift_samples_col().insert_one(sample.model_dump())

    if alert:
        print(f"[BEACON DRIFT ALERT] score dropped {delta_pct:.1f} pts below baseline "
              f"({baseline_score * 100:.1f}% -> {current_score * 100:.1f}%)")

    return sample
