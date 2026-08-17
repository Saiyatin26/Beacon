"""Stage 2 orchestrator — runs the full invariant mining sub-pipeline:
candidate -> evidence -> validation -> contradiction check -> confidence -> (dedup+store, spec, or discard).

This is the module backend/api/main.py and scripts/run_demo_pipeline.py call.
"""

from typing import Callable, Union
from common.models import ValidatedInvariant, UnconfirmedCandidate
from evidence.models import UnifiedEvidencePackage
from .offline_miner import OfflineCandidateGenerator
from .candidate_generator import LLMCandidateGenerator
from .evidence_collector import collect_evidence
from .validator import validate_candidate
from .confidence_scorer import score_confidence
from . import dedup, spec_provenance


def run_mining_pipeline(
    evidence_package: UnifiedEvidencePackage,
    legacy_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    already_validated: list[ValidatedInvariant],
    use_atlas: bool = True,
    use_llm: bool = False,
) -> tuple[list[ValidatedInvariant], list[UnconfirmedCandidate]]:
    """Runs the full candidate generation and validation pipeline."""
    
    # 1. Candidate Generation
    if use_llm:
        generator = LLMCandidateGenerator()
    else:
        generator = OfflineCandidateGenerator()
        
    candidates = generator.propose_candidates(evidence_package)
    
    graduated_invariants = []
    unconfirmed_candidates = []
    
    for candidate in candidates:
        if use_atlas:
            similar = dedup.find_similar(candidate.condition)
            if similar:
                # Already mined under different wording — skip re-validation.
                existing = similar[0]
                graduated_invariants.append(ValidatedInvariant(
                    invariant_id=existing["invariant_id"],
                    condition=existing["condition"],
                    consequence=existing["consequence"],
                    severity=candidate.severity,
                    evidence_ids=candidate.evidence_ids,
                    generation_method=candidate.generation_method,
                    timestamp=candidate.timestamp,
                    rationale=candidate.rationale,
                    source_lines=candidate.source_lines,
                    confidence=1.0,
                    graduated=True,
                ))
                continue

        # 2. Evidence Collection
        evidence = collect_evidence(candidate, evidence_package.runtime_traces, corpus_size=len(evidence_package.runtime_traces))
        
        # 3. Adversarial Validation & Contradiction Check
        validation = validate_candidate(candidate, legacy_fn, field_bounds, already_validated)
        
        # 4. Confidence Scoring & Gate
        result = score_confidence(candidate, evidence, validation)

        if isinstance(result, ValidatedInvariant) and result.graduated:
            graduated_invariants.append(result)
            spec_provenance.write_proposal(result, evidence, validation)
            if use_atlas:
                dedup.store_invariant(result.model_dump(), result.condition)
        else:
            unconfirmed_candidates.append(result)

    return graduated_invariants, unconfirmed_candidates
