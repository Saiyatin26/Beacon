"""Stage 4 — Certification run orchestrator.

Runs the full oracle set against a candidate ('modernized') implementation,
scores it, and builds the CertificationRun report matching the format in the
architecture doc Section 7.4 (overall score, domain breakdown, severity
breakdown, per-violation detail with counterexamples).
"""

import uuid
from datetime import datetime, timezone
from typing import Callable
from common.models import Oracle, CertificationRun, Violation
from oracle.interpreter import run_oracle
from .scorer import equivalence_score, domain_scores


def certify(
    oracles: list[Oracle],
    modern_fn: Callable[..., dict],
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    domain_of: dict[str, str] | None = None,
) -> CertificationRun:
    oracles_by_id = {o.invariant_id: o for o in oracles}
    results = [run_oracle(o, modern_fn, field_bounds) for o in oracles]

    violations = []
    for result in results:
        if result["violated"] > 0 and result["counterexample"]:
            oracle = oracles_by_id[result["invariant_id"]]
            ce = result["counterexample"]
            legacy_actual = legacy_fn(**ce["inputs"])
            violations.append(Violation(
                invariant_id=oracle.invariant_id,
                expected=oracle.property,
                legacy_output=str(legacy_actual.get("decision", "")).upper(),
                modern_output=ce["actual"],
                counterexample=ce["inputs"],
                confidence=oracle.confidence,
                severity=oracle.severity,
            ))

    score = equivalence_score(results, oracles_by_id)
    domains = domain_scores(results, oracles_by_id, domain_of or {})

    return CertificationRun(
        run_id=str(uuid.uuid4())[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        equivalence_score=score,
        domain_scores=domains,
        violations=violations,
        total_checked=sum(r["checked"] for r in results),
        total_violated=sum(r["violated"] for r in results),
    )
