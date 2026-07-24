"""Stage 2b — Evidence collection.

For a candidate invariant, counts how many traces corroborate it and how
diverse those corroborating inputs are. Input diversity matters as much as
raw count (architecture doc Section 7.1): a rule seen 500 times on
near-identical inputs is weaker evidence than one seen 20 times spread across
the input space.
"""

import math
from common.dsl_eval import eval_condition
from common.models import CandidateInvariant, EvidenceReport, TraceEvent


def _condition_holds(candidate: CandidateInvariant, trace: TraceEvent) -> bool:
    try:
        return eval_condition(candidate.condition, trace.inputs)
    except Exception:
        return False


def _output_matches(candidate: CandidateInvariant, trace: TraceEvent) -> bool:
    return str(trace.output.get("decision", "")).upper() == candidate.consequence.upper()


def _diversity(corroborating_inputs: list[dict]) -> float:
    """Normalized spread of numeric input fields across corroborating traces.
    Simple stand-in metric: average coefficient of variation across numeric
    fields, clamped to [0, 1]."""
    if len(corroborating_inputs) < 2:
        return 0.0
    numeric_fields = [
        k for k, v in corroborating_inputs[0].items() if isinstance(v, (int, float))
    ]
    if not numeric_fields:
        return 0.0
    scores = []
    for field in numeric_fields:
        values = [t[field] for t in corroborating_inputs]
        mean = sum(values) / len(values)
        if mean == 0:
            continue
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        scores.append(min(std / abs(mean), 1.0))
    return sum(scores) / len(scores) if scores else 0.0


def collect_evidence(
    candidate: CandidateInvariant, traces: list[TraceEvent], corpus_size: int
) -> EvidenceReport:
    corroborating = [
        t for t in traces if _condition_holds(candidate, t) and _output_matches(candidate, t)
    ]
    count = len(corroborating)
    return EvidenceReport(
        invariant_id=candidate.invariant_id,
        evidence_count=count,
        evidence_count_norm=min(count / max(corpus_size, 1), 1.0),
        input_diversity=_diversity([t.inputs for t in corroborating]),
    )
