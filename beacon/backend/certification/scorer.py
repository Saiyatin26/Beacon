"""Stage 4 — Equivalence scoring.

Implements the formula from the architecture doc, Section 7.3:

    equivalence_score = sum(severity_weight_i * confidence_i * pass_i)
                       / sum(severity_weight_i * confidence_i)

Weighting by both severity and confidence means a low-confidence invariant
contributes less to the headline score even if it fails, so a shaky candidate
rule can't artificially tank the reported result.
"""

from common.config import settings
from common.models import Oracle


def equivalence_score(oracle_results: list[dict], oracles_by_id: dict[str, Oracle]) -> float:
    numerator, denominator = 0.0, 0.0
    for result in oracle_results:
        oracle = oracles_by_id[result["invariant_id"]]
        weight = settings.severity_weights[oracle.severity] * oracle.confidence
        numerator += weight * result["pass_i"]
        denominator += weight
    return round(numerator / denominator, 4) if denominator else 1.0


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
