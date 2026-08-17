"""Stage 2d — Confidence scoring.

Implements the formula from the architecture doc, Section 7.1:

    confidence_i = w1*evidence_count_norm + w2*input_diversity
                 + w3*boundary_pass_rate - w4*contradiction_penalty

Weights are a starting point (equal-ish, contradiction heavily penalized) —
architecture doc Section 9 flags these as provisional and tunable against real
sample data.
"""

from typing import Union
from common.config import settings
from common.models import CandidateInvariant, EvidenceReport, ValidationReport, ValidatedInvariant, UnconfirmedCandidate

WEIGHTS = {"evidence": 0.15, "diversity": 0.15, "boundary": 0.7, "contradiction": 0.5}


def score_confidence(
    candidate: CandidateInvariant,
    evidence: EvidenceReport,
    validation: ValidationReport,
) -> Union[ValidatedInvariant, UnconfirmedCandidate]:
    contradiction_penalty = min(validation.contradiction_count * 0.5, 1.0)

    confidence = (
        WEIGHTS["evidence"] * evidence.evidence_count_norm
        + WEIGHTS["diversity"] * evidence.input_diversity
        + WEIGHTS["boundary"] * validation.boundary_pass_rate
        - WEIGHTS["contradiction"] * contradiction_penalty
    )
    confidence = max(0.0, min(1.0, confidence))

    if confidence >= settings.confidence_threshold:
        return ValidatedInvariant(
            invariant_id=candidate.invariant_id,
            condition=candidate.condition,
            consequence=candidate.consequence,
            severity=candidate.severity,
            evidence_ids=candidate.evidence_ids,
            generation_method=candidate.generation_method,
            timestamp=candidate.timestamp,
            rationale=candidate.rationale,
            source_lines=candidate.source_lines,
            confidence=round(confidence, 4),
            graduated=True,
        )
    else:
        return UnconfirmedCandidate(
            invariant_id=candidate.invariant_id,
            condition=candidate.condition,
            consequence=candidate.consequence,
            severity=candidate.severity,
            evidence_ids=candidate.evidence_ids,
            generation_method=candidate.generation_method,
            timestamp=candidate.timestamp,
            rationale=candidate.rationale,
            source_lines=candidate.source_lines,
            confidence=round(confidence, 4),
        )
