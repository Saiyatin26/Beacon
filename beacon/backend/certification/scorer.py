"""Stage 4 — Equivalence scoring.

Implements the formula from the architecture doc, Section 7.3:

    equivalence_score = sum(severity_weight_i * confidence_i * pass_i)
                       / sum(severity_weight_i * confidence_i)

Weighting by both severity and confidence means a low-confidence invariant
contributes less to the headline score even if it fails, so a shaky candidate
rule can't artificially tank the reported result.
"""

import math

from common.config import settings
from common.models import Oracle


EVIDENCE_SCORE_WEIGHTS = {
    "oracle_coverage": 0.30,
    "input_coverage": 0.20,
    "execution_reliability": 0.20,
    "oracle_confidence": 0.15,
    "input_set_integrity": 0.10,
    "source_hash_integrity": 0.05,
}


def evidence_adjusted_score(
    behavioral_score: float,
    factors: dict[str, float | None],
) -> tuple[float, float, dict[str, float]]:
    """Combines observed equivalence with available, run-derived evidence quality factors."""
    if not math.isfinite(behavioral_score) or not 0.0 <= behavioral_score <= 1.0:
        raise ValueError("behavioral_score must be finite and between 0.0 and 1.0")

    active_factors: dict[str, float] = {}
    for name in EVIDENCE_SCORE_WEIGHTS:
        value = factors.get(name)
        if value is None:
            continue
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"Evidence factor '{name}' must be finite and between 0.0 and 1.0")
        active_factors[name] = value

    total_weight = sum(EVIDENCE_SCORE_WEIGHTS[name] for name in active_factors)
    if total_weight == 0.0:
        raise ValueError("At least one evidence factor is required")

    quality = sum(
        EVIDENCE_SCORE_WEIGHTS[name] * value
        for name, value in active_factors.items()
    ) / total_weight
    adjusted_score = behavioral_score * quality
    return round(adjusted_score, 6), round(quality, 6), active_factors


def equivalence_score(oracle_results: list[dict], oracles_by_id: dict[str, Oracle]) -> float:
    numerator, denominator = 0.0, 0.0
    for result in oracle_results:
        oracle = oracles_by_id[result["invariant_id"]]
        weight = settings.severity_weights[oracle.severity] * oracle.confidence
        numerator += weight * result["pass_i"]
        denominator += weight
    return round(numerator / denominator, 4) if denominator else 0.0


def domain_scores(oracle_results: list[dict], oracles_by_id: dict[str, Oracle],
                   domain_of: dict[str, str]) -> dict[str, float]:
    """Breaks the score down by business domain (architecture doc Section 7.4).
    domain_of maps invariant_id -> domain label, assigned at tagging time."""
    by_domain: dict[str, list[dict]] = {}
    for result in oracle_results:
        domain = domain_of.get(result["invariant_id"], "Uncategorized")
        by_domain.setdefault(domain, []).append(result)

    return {
        domain: equivalence_score(results, oracles_by_id)
        for domain, results in by_domain.items()
    }
