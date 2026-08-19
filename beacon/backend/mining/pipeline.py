"""Stage 2 orchestrator — runs the full invariant mining sub-pipeline:
UnifiedEvidencePackage -> Candidate Generator -> Evidence Collection -> Adversarial Validation -> Contradiction Check -> Confidence Score -> 0.8 Gate.

This is the module backend/api/main.py and scripts/run_demo_pipeline.py call.
"""

from typing import Callable, Optional
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
    already_validated: Optional[list[ValidatedInvariant]] = None,
    use_atlas: bool = True,
    use_llm: bool = False,
) -> tuple[list[ValidatedInvariant], list[UnconfirmedCandidate]]:
    """Runs the canonical candidate generation and validation pipeline."""
    
    # 1. Candidate Generation (Offline or LLM)
    if use_llm:
        generator = LLMCandidateGenerator()
    else:
        generator = OfflineCandidateGenerator()
        
    candidates = generator.propose_candidates(evidence_package)
    
    graduated_invariants: list[ValidatedInvariant] = []
    unconfirmed_candidates: list[UnconfirmedCandidate] = []
    current_validation_context: list[ValidatedInvariant] = list(already_validated or [])
    
    for candidate in candidates:
        # 2. Evidence Collection directly from UnifiedEvidencePackage
        evidence = collect_evidence(candidate, evidence_package)
        
        # 3. Adversarial / Property-Based Validation & Contradiction Check against accumulated context
        validation = validate_candidate(candidate, legacy_fn, field_bounds, current_validation_context)
        
        # 4. Confidence Scoring & 0.8 Confidence Gate
        result = score_confidence(candidate, evidence, validation)

        if isinstance(result, ValidatedInvariant) and result.graduated:
            graduated_invariants.append(result)
            current_validation_context.append(result)  # Dynamically add to validation context for subsequent checks
            spec_provenance.write_proposal(result, evidence, validation)
            if use_atlas:
                dedup.store_invariant(result.model_dump(), result.condition)
        else:
            unconfirmed_candidates.append(result)

    return graduated_invariants, unconfirmed_candidates
