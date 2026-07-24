"""Stage 2 orchestrator — runs the full invariant mining sub-pipeline:
candidate -> evidence -> validation -> confidence -> (dedup+store, spec, or discard).

This is the module backend/api/main.py and scripts/run_demo_pipeline.py call.
"""

from typing import Callable
from common.models import CandidateInvariant, TraceEvent, ValidatedInvariant
from .candidate_generator import propose_candidate
from .evidence_collector import collect_evidence
from .validator import validate_candidate
from .confidence_scorer import score_confidence
from . import dedup, spec_provenance


def mine_one_invariant(
    source_code: str,
    traces: list[TraceEvent],
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    already_validated: list[ValidatedInvariant],
    use_atlas: bool = True,
) -> ValidatedInvariant:
    trace_dicts = [t.model_dump() for t in traces]

    candidate: CandidateInvariant = propose_candidate(source_code, trace_dicts)

    if use_atlas:
        similar = dedup.find_similar(candidate.condition)
        if similar:
            # Already mined under different wording — skip re-validation.
            existing = similar[0]
            return ValidatedInvariant(
                invariant_id=existing["invariant_id"],
                condition=existing["condition"],
                consequence=existing["consequence"],
                severity=candidate.severity,
                confidence=1.0,
                graduated=True,
            )

    evidence = collect_evidence(candidate, traces, corpus_size=len(traces))
    validation = validate_candidate(candidate, legacy_fn, field_bounds, already_validated)
    validated = score_confidence(candidate, evidence, validation)

    if validated.graduated:
        spec_provenance.write_proposal(validated, evidence, validation)
        if use_atlas:
            dedup.store_invariant(validated.model_dump(), validated.condition)

    return validated
