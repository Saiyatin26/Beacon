"""Stage 2d — Confidence scoring.

Implements the formula from the architecture doc, Section 7.1:

    confidence_i = w1*evidence_count_norm + w2*input_diversity
                 + w3*boundary_pass_rate - w4*contradiction_penalty

Enforces the 0.8 confidence gate and records full provenance on all candidates.
"""

from typing import Union
from common.config import settings
from common.models import (
    CandidateInvariant,
    EvidenceReport,
    ValidationReport,
    ValidatedInvariant,
    UnconfirmedCandidate,
)

WEIGHTS = {"evidence": 0.20, "diversity": 0.20, "boundary": 0.60, "contradiction": 0.50}


def score_confidence(
    candidate: CandidateInvariant,
    evidence: EvidenceReport,
    validation: ValidationReport,
) -> Union[ValidatedInvariant, UnconfirmedCandidate]:
    contradiction_penalty = min(validation.contradiction_count * 0.5, 1.0)

    raw_confidence = (
        WEIGHTS["evidence"] * evidence.evidence_count_norm
        + WEIGHTS["diversity"] * evidence.input_diversity
        + WEIGHTS["boundary"] * validation.boundary_pass_rate
        - WEIGHTS["contradiction"] * contradiction_penalty
    )
    confidence = max(0.0, min(1.0, raw_confidence))
    confidence_rounded = round(confidence, 4)

    # Attach confidence components for complete provenance
    candidate.confidence_components = {
        "evidence_count_norm": evidence.evidence_count_norm,
        "input_diversity": evidence.input_diversity,
        "boundary_pass_rate": validation.boundary_pass_rate,
        "contradiction_penalty": contradiction_penalty,
        "condition_coverage": validation.condition_coverage,
        "raw_confidence": confidence_rounded,
    }

    if confidence_rounded >= settings.confidence_threshold:
        return ValidatedInvariant(
            invariant_id=candidate.invariant_id,
            condition=candidate.condition,
            consequence=candidate.consequence,
            source_file=candidate.source_file,
            source_lines=candidate.source_lines,
            severity=candidate.severity,
            evidence_ids=candidate.evidence_ids,
            execution_ids=candidate.execution_ids,
            generation_method=candidate.generation_method,
            timestamp=candidate.timestamp,
            rationale=candidate.rationale,
            confidence_components=candidate.confidence_components,
            validation_result=candidate.validation_result,
            confidence=confidence_rounded,
            graduated=True,
            status="graduated",
        )
    else:
        return UnconfirmedCandidate(
            invariant_id=candidate.invariant_id,
            condition=candidate.condition,
            consequence=candidate.consequence,
            source_file=candidate.source_file,
            source_lines=candidate.source_lines,
            severity=candidate.severity,
            evidence_ids=candidate.evidence_ids,
            execution_ids=candidate.execution_ids,
            generation_method=candidate.generation_method,
            timestamp=candidate.timestamp,
            rationale=candidate.rationale,
            confidence_components=candidate.confidence_components,
            validation_result=candidate.validation_result,
            confidence=confidence_rounded,
            graduated=False,
            status="unconfirmed",
        )
